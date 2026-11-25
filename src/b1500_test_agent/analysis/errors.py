"""Errors of the analysis layer; each carries the ``ErrorCode`` that ``analyze_run``/``get_run`` report.

Exceptions mean the *call* cannot be served (unknown run, malformed run folder, bad options). A call that is served
but whose data do not allow a trustworthy value returns an ``ExtractionResult`` with ``outcome`` ``refused`` or
``failed`` and ``value=None`` instead of raising.
"""

from __future__ import annotations

from b1500_test_agent.errors import InvalidInputError


class RunNotFoundError(InvalidInputError):
    """No run folder with a ``manifest.json`` exists for the run id (derived folder and ``runs/index.jsonl``)."""


class RunFormatError(InvalidInputError):
    """A run folder breaks the archive contract: invalid manifest, missing or malformed run table (``data.csv`` or
    ``data.npz``) or run file, digest mismatch."""
