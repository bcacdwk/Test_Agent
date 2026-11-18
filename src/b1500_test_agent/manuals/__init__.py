"""Local manual corpus (blueprint 5): the Keysight manuals as searchable page text, without the PDFs.

- ``catalog`` – ``references/manuals/catalog.yaml`` and ``synonyms.yaml``, the manuals folder
  (``Settings.manuals_dir`` / ``B1500_MANUALS_DIR``) and locating each PDF by path or sha256.
- ``build`` – ``b1500 manual build [--check]``: PDF pages → ``references/manuals/corpus/pages.jsonl.gz`` +
  ``outline.json`` (pypdfium2; deterministic bytes).
- ``search`` – the read-only queries ``search`` (pure-Python BM25), ``page``, ``toc`` and ``status``; without a
  corpus they answer from the structured extracts and say how to build it.

Layering: imports only ``models`` and ``paths`` from this package (blueprint 2.1); the CLI (``adapters/cli/manual.py``),
``b1500 doctor`` and the citation lint (``devtools/skills/citations.py``) use it. Nothing here talks to an instrument.
"""

from b1500_test_agent.manuals.catalog import ENV_MANUALS_DIR, ManualError, ManualPaths, load_catalog

__all__ = ["ENV_MANUALS_DIR", "ManualError", "ManualPaths", "load_catalog"]
