"""Shared constants and helpers of the service facade: response budget, token estimate, argument digest, error-code
to status mapping and small formatting helpers (blueprint 5.1)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any, Final

import numpy as np
from pydantic import ValidationError

from b1500_test_agent.models.analysis import ExtractionResult
from b1500_test_agent.models.common import ErrorCode, ResultStatus
from b1500_test_agent.models.results import GetRunSection

TOOL_NAMES: Final[tuple[str, ...]] = (
    "station_status", "list_recipes", "validate_plan", "run_plan", "run_confirmed_plan",
    "list_runs", "get_run", "analyze_run", "annotate_run", "safe_shutdown",
)  # fmt: skip
"""The ten MCP tools of blueprint 5.1, in table order; ``B1500Service`` has one method per name."""

ENV_SESSION_TAG = "B1500_SESSION_TAG"
RESPONSE_TOKEN_BUDGET: Final = 2000
TRIM_TARGET: Final = 1900
"""Responses are trimmed until ``approx_tokens`` of their JSON is at most this (5 % below the 2k budget)."""
DEFAULT_MAX_POINTS: Final = 200
NPZ_MAX_POINTS: Final = 200
"""Rows ``get_run`` returns at most for a ``data.npz`` run (> 200,000 points), whatever ``max_points`` asks."""
MAX_POINTS_LIMIT: Final = 10_000
DEFAULT_RUN_LIMIT: Final = 20
MAX_RUN_LIMIT: Final = 200
DEFAULT_SECTIONS: Final[tuple[GetRunSection, ...]] = ("summary", "quality")
AUDIT_LINES: Final = 20
NOTE_TEXT_MAX: Final = 2000
NOTE_TAGS_MAX: Final = 10
NOTE_EXCERPT_MAX: Final = 500
REASON_MAX: Final = 200
MESSAGE_MAX: Final = 1000
TAG_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
_TOKEN_RE = re.compile(r"[A-Z]+|[a-z]+|\d{1,3}|[!-/:-@\[-`{-~]{1,2}|[^\x00-\x7f]+| (?=\d)")

CONFIG_STEPS = [("station_status lists the configuration problems; ask the human to fix config/local/ "
                "(b1500 config check); never edit it yourself")]
_REFUSED_CODES = frozenset({"invalid_input", "unknown_plan", "plan_expired", "plan_stale", "blocked_by_rules",
                            "confirmation_required", "summary_mismatch"})


def value_text(result: ExtractionResult) -> str:
    """``quantity = value unit`` with ``<=``/``>=`` for bounds and the classification, if any."""
    relation = {"exact": "=", "upper": "<=", "lower": ">="}[result.bound]
    tail = f" ({result.classification})" if result.classification else ""
    return f"{result.quantity} {relation} {result.value:.4g} {result.unit}{tail}"


def approx_tokens(text: str) -> int:
    """Conservative token estimate for budget checks, without a tokenizer download: one token per lower-case or
    upper-case letter run (upper-case runs longer than two letters count one per two letters), per group of up to
    three digits, per pair of ASCII punctuation characters and per space before a digit; non-ASCII text counts
    1.25 tokens per character. For tool-result JSON it counts 3-30 % more than ``o200k_base`` (tests check it);
    responses are trimmed to ``TRIM_TARGET`` by this estimate, 5 % below ``RESPONSE_TOKEN_BUDGET``."""
    count = 0
    for match in _TOKEN_RE.finditer(text):
        piece = match.group()
        if piece[0] >= "\x80":
            count += len(piece) + len(piece) // 4
        elif len(piece) > 2 and piece.isupper():
            count += (len(piece) + 1) // 2
        else:
            count += 1
    return count


def args_digest(args: Mapping[str, Any]) -> str:
    """sha256 (first 16 hex digits) of the canonical JSON of a call's arguments."""
    text = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:16]


def status_for(code: ErrorCode) -> ResultStatus:
    """The result status that goes with an error code."""
    if code in _REFUSED_CODES:
        return "refused"
    if code == "instrument_busy":
        return "busy"
    if code in ("fault_latched", "cleanup_unverified"):
        return "fault"
    return "error"


def validation_message(exc: ValidationError) -> str:
    """A one-line ``invalid input`` message from a pydantic error (first five problems: field path and reason)."""
    problems = [f"{'.'.join(str(p) for p in e.get('loc', ())) or 'input'}: {e.get('msg', '')}"
                for e in exc.errors()[:5]]
    return "invalid input: " + "; ".join(problems)


def clip(text: str, limit: int = MESSAGE_MAX) -> str:
    """``text`` cut to ``limit`` characters (``...`` marks a cut)."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def round_cell(value: Any) -> float | int | str | None:
    """A JSON-friendly table cell: floats to 4 significant digits, NaN → ``None``."""
    if value is None:
        return None
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        if not math.isfinite(number):
            return None
        return float(f"{number:.4g}")
    return str(value)


def sample_indices(n: int, k: int) -> list[int]:
    """At most ``k`` evenly spaced row indices of ``n`` rows, first and last included."""
    if n <= k:
        return list(range(n))
    if k <= 1:
        return [0]
    return sorted({int(i) for i in np.linspace(0, n - 1, k).round()})
