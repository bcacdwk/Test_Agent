# Manual Sources

The Keysight manuals are indexed by `catalog.yaml` (16 PDFs: id, file, edition, sha256, pages, printed-label rule)
and searchable without the PDFs through the committed page corpus in `corpus/` (`uv run b1500 manual search|page|toc`;
rebuild with `uv run b1500 manual build`). Usage, citation style (`PG p433 (4-115)`) and maintenance:
[`docs/manuals.md`](../../docs/manuals.md). The PDFs live outside the repository (`settings.manuals_dir`, default the
clone's parent, or `B1500_MANUALS_DIR`) and are never committed.

| Path | Content | Edited by |
|---|---|---|
| `catalog.yaml`, `synonyms.yaml` | Document catalog and search synonyms | developers (then `b1500 manual build`) |
| `corpus/pages.jsonl.gz`, `corpus/outline.json` | Page text and PDF outlines (generated) | `b1500 manual build` only |
| `*-index.md`, `structured/` | Hand-curated indexes and extracts with PDF page references (v1) | read-only |

Do not paste large manual sections into skills or docs: extract concise facts, command syntax, constraints and
caveats, and cite the page. Every extracted item names its source document and page.
