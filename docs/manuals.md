# Manuals: corpus, search and citations

The Keysight manuals are reachable from any clone without the PDFs: a committed page corpus answers
`b1500 manual search|page|toc|status`, and every manual citation in skills, recipes, source docstrings and docs is
checked against it. Plan of record: [blueprint §5](design/blueprint.md#5-manual-knowledge-access) (decisions 13–16,
OD-1). Code: `src/b1500_test_agent/manuals/` (`catalog`, `build`, `search`), CLI `adapters/cli/manual.py`, lint
`devtools/skills/citations.py`.

## What is committed (and what never is)

| Path | Content |
|---|---|
| `references/manuals/catalog.yaml` | The 16 indexed PDFs: id, file (relative to the manuals folder), title, edition, part number, sha256, size, pages, language, kind, search `priority`, printed-label rule, the private-use glyph table, and the curated extracts of each manual. No manual text. |
| `references/manuals/synonyms.yaml` | A few query synonyms (`selector → ERSSP ERMOD 16440A`, `开路 → open`), used only when nothing matches. |
| `references/manuals/corpus/pages.jsonl.gz` | One JSON line per PDF page: `{doc, p, printed, outline_path, text}` (2,315 pages, about 0.7 MB). Deterministic gzip. |
| `references/manuals/corpus/outline.json` | Every PDF outline (PG has one entry per command, WG one per library function), each document's source sha256, page and character counts, and the catalog digest the corpus was built from. |
| `references/manuals/{*-index.md,structured/}` | Hand-curated indexes and extracts (read-only; v1). They answer queries when no corpus is built. |

PDFs are never committed (OD-1: the repository is private; page text only). `b1500 doctor` reports the corpus
(`manual corpus`: PASS when current) and the PDFs (`manual PDFs`: INFO when absent — they are optional).

## Documents

| Id | Manual | Edition | Pages | File (in the manuals folder) |
|---|---|---|---|---|
| PG | B1500A/B1505A/B1506A/B1507A Programming Guide (FLEX commands) | Ed. 15, May 2022 | 617 | `B1500A Programming Guide.pdf` |
| EX | EasyEXPERT Software User's Guide, Vol. 1 + 2 | Ed. 5, Dec 2020 | 700 | `Keysight EasyEXPERT Software.pdf` |
| UG | B1500A User's Guide | Ed. 17, Feb 2021 | 160 | `B1500A User Guide.pdf` |
| WG | B1530A WGFMU User's Guide (current) | Ed. 8, Feb 2021 | 160 | `lwp/matlab_B1500/9018-01706.pdf` |
| WG5 | B1530A WGFMU User's Guide (cited by the v1 extracts) | Ed. 5, Aug 2012 | 164 | `B1530A WGFMU.pdf` |
| CC | B1500A Configuration and Connection Guide | Ed. 10, Nov 2020 | 122 | `Keysight B1500A Configuration and Connection Guide.pdf` |
| AC | B1500A configuration guide (accessories) | 5992-2417EN, 2024 | 24 | `B1500A Accessories.pdf` |
| SEL | 16440A SMU/Pulse Generator Selector User's Guide | Ed. 6, Aug 2014 | 32 | `Keysight 16440A SMUPulse Generator Selector.pdf` |
| DS | B1500A 技术概述 (data sheet, Chinese) | 5991-2443CHCN, 2019 | 17 | `B1500A 半导体器件分析仪 产品技术手册.pdf` |
| AN-REL | CMOS 可靠性测试解决方案 (reliability) | 5990-5896CHCN, 2019 | 10 | `Demo/…` |
| AN-CHAR | CMOS 器件电性表征 (characterization) | 5990-5566CHCN, 2014 | 7 | `Demo/…` |
| AN-TUT | B1500A 自学培训教程 (self-paced tutorial, mostly images) | 第 9 版, 2021 | 186 | `Demo/…` |
| AN-NVM | EasyEXPERT Advanced NVM Application Tests | Ed. 1, Jun 2019 | 90 | `Demo/…` |
| AN-RTN | WGFMU 随机电报噪声 (RTN) 测量 | 5990-3705CHCN, 2019 | 10 | `Demo/…` |
| AN-CV | MFCMU 和 SCUU 的 IV/CV 测量 | 5989-3608CHCN, 2019 | 8 | `Demo/…` |
| AN-FIV | B1530A 闪存单元 1 μs IV 特性 | 5990-3636CHCN, 2014 | 8 | `Demo/…` |

`lwp/matlab_B1500/B1500_Programing_Guide.pdf` is the same PG Edition 15 text and is not indexed; any other extra file
in the folder is ignored.

## Querying (read-only, `--json` on every command)

```bash
uv run b1500 manual search "ERSSP status"                 # PG p433 (4-115) · ERSSP · <snippet>
uv run b1500 manual search WGFMU_setMeasureEvent --doc WG,WG5 -k 3
uv run b1500 manual search 随机电报噪声 --json
uv run b1500 manual page PG 433 --to 435                  # at most 3 pages, --max-chars 6000 in total
uv run b1500 manual page PG --printed 4-189               # = PDF 507 (SER)
uv run b1500 manual toc PG --grep FMT                     # outline entries with PDF page and printed label
uv run b1500 manual status                                # corpus current/stale/missing; PDFs found
```

- **Search** is pure-Python BM25 built in memory per call (about 0.2 s over all 2,315 pages; no index file).
  Tokens: ASCII words and FLEX mnemonics whole (`erssp`, `b1500a`), `WGFMU_*` names whole, Chinese as character
  bigrams; text is NFKC-folded, so `µA` = `μA` and full-width letters match ASCII. All terms must match; with zero
  hits any term may match; still zero, the synonyms are added. An outline entry whose title is a command or function
  name equal to a query word (`ERSSP`, `WGFMU_setMeasureEvent`) ranks its page first, the more authoritative
  document first (`priority`: PG, WG, SEL, CC boosted; WG5 lowered). Exit code 1 when nothing matches.
- **Page** numbers are physical 1-based PDF pages (what a PDF viewer shows). `--printed` finds a page by the label
  printed in its header or footer (`4-189`, `2-17`, `9`); chapter title pages carry the label their numbering
  implies (`2-1` before `2-2`). Unknown documents and pages out of range exit with code 2.
- **Agents**: the curated knowledge files first; then `manual search` → `manual page` for ground truth; cite the page,
  never paste long passages.

## Citations

Write `PG p433 (4-115)`: document id, PDF page, printed label in parentheses (optional but checked), optionally a
quoted keyword that must occur on the page: `PG p433 (4-115) "ERSSP"`. Ranges read `PG p433-434`. The v1 form
`PG PDF 380, printed 4-62` (also `WG Ed. 5 PDF 24` = WG5) stays valid and is checked the same way.

`uv run b1500 dev lint-skills` (and pytest, `tests/skills/test_citations.py`) checks every citation in
`.agents/skills/`, `recipes/`, `src/b1500_test_agent/` and `docs/` (plus `README.md`, `AGENTS.md`): the id is in the
catalog (any `AN-…` id counts as a citation, so an unknown one fails), the pages exist, and — with the committed
corpus — the printed label and keyword match. `references/` is not linted. A failing citation is fixed in the citing
text, never by loosening the lint.

## The manuals folder

`settings.manuals_dir` (default `..`, the clone's parent, relative to the repository root) or `B1500_MANUALS_DIR`
(wins). On the Mac the clone sits inside the folder that holds the PDFs; on the lab PC
(`C:\b1500\test_agent`) copy the PDFs to `C:\b1500\` only if you want figures or to rebuild — the committed corpus
answers every query without them. A PDF is found at its catalog path, else anywhere up to four folders deep by
size and sha256 (renamed copies work; hidden folders, `.venv` and the clone itself are skipped).

## Building and checking the corpus (developers)

```bash
uv run b1500 manual build                     # all 16 PDFs needed; writes references/manuals/corpus/ (about 2 s)
uv run b1500 manual build --check             # rebuild in memory, compare byte for byte, write nothing
uv run b1500 manual build --src D:/manuals    # PDFs elsewhere (same as B1500_MANUALS_DIR)
```

- A build refuses to write when a catalog PDF is missing. A PDF with another sha256 at the catalog path is an
  *edition mismatch*: a warning, and the build uses that file.
- `--check` compares both files byte for byte when every PDF is present, per document otherwise; with no PDF at all
  it reports "not verified" (exit 0). A gzip stream that differs only because another zlib compressed the same JSON
  lines is reported as reproduced content.
- Extraction is PDFium's text layer (`pypdfium2`, pinned by `uv.lock`; no OCR, so the image-only slides of AN-TUT
  contribute little text). Normalisation: PDFium's hyphenation marks join words; the manuals' Symbol/Wingdings
  glyphs (U+F0xx) become `µ Ω ± ≤ ≥ × °` … via the catalog `symbols` table (an unlisted one is dropped and reported);
  table-of-contents leader dots become `...`.
- **New edition of a manual**: replace the PDF, update its catalog entry (`sha256`, `size`, `pages`, `edition`,
  `label_rule` if the running header changed), run `uv run b1500 manual build`, then `uv run b1500 dev lint-skills`
  and fix the citations whose pages moved. Commit the catalog and both corpus files together (corpus ≤ 1 MB, OD-1).

## Without a corpus

If `references/manuals/corpus/` is missing (deleted, or a fixture tree), every command still answers, from the
structured extracts the catalog lists per document (`extracts:`): search over index-table rows, paragraphs and YAML
items; `page` shows what the extracts say about that PDF page; `toc` lists their headings and index rows. Each
answer says so and how to build the corpus. WG (Edition 8) has no extract; the WGFMU extracts cite WG5 pages.

## Structured extracts (v1)

`references/manuals/` also holds the hand-curated indexes (`b1500a-programming-guide-index.md`,
`b1530a-wgfmu-index.md`, `keysight-easyexpert-software-index.md`) and `structured/` extracts (FLEX command summary
and parameters, error codes, initial settings, WGFMU API, timing and examples, EasyEXPERT catalogs). They are
read-only inputs: their "PDF N" numbers are physical pages of the editions named in each file (WGFMU: Edition 5 =
WG5). Driver work still reads exact syntax from PG and records `PG PDF N` / `PG pN (X-Y)` in each builder docstring
and in `references/driver-map/flex-driver-map.yaml`; parser and simulator fixtures in `tests/fixtures/flex/` carry
the page they were transcribed from.

## Not built (by decision)

Embeddings, a vector database, network fetches and an MCP tool. The reserve is an 11th read-only tool
`manual_search` (about 130 tokens), only if a harness cannot run the CLI without prompts (OD-5, ATV-25).
