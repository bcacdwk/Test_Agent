"""Run datasets: the tidy ``data.csv`` contract, run lookup and ``RunData`` (blueprint 2.7, 2.8).

This module is the single definition of the run-table contract; the archive writer (WP1.7) builds tables with
``with_trust`` and writes them with ``write_table``, and places run folders at ``run_relpath``.

**Run folder.** ``<data_root>/runs/<yyyy>/<mm>/<dd>/<run_id>/`` with ``manifest.json`` (``RunManifest``) and
``data.csv``. The date folders come from the run id (``S|H`` + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex).
``runs/index.jsonl`` holds one JSON object per finalized run with at least ``run_id`` and ``path`` (the run folder
relative to ``runs/``, POSIX separators, e.g. ``2026/11/17/S20261117T063012Z-7f3a``); ``load_run`` falls back to it
when the derived folder has no manifest.

**data.csv** (UTF-8 without BOM, ``\\n`` line ends, written with ``newline=""``, one header row, one row per
measurement point in acquisition order):

- ``step``: 0-based point index in acquisition order; integers, strictly increasing.
- ``<role>_<qty>``: a value of recipe role ``<role>`` (lower-case identifier, may contain ``_``); ``<qty>`` is ``V``
  (volts) or ``I`` (amperes). With a status column it is a measured value; without one it is the programmed source
  value (e.g. ``gate_V`` of a swept gate whose voltage is not measured). Never both for the same name. Empty cells
  are missing values; the invalid-data value ``199.999E+99`` is kept as read.
- ``<role>_<qty>_status``: the single-letter measurement status of that value (``N`` normal, ``C``/``T``
  compliance, ``V X F D G S U`` invalid; any other letter is untrusted), exactly one upper-case letter.
- ``segment`` (double sweeps only): ``fwd`` or ``rev``.
- ``trust``: ``ok``, ``limited`` or ``untrusted``: the worst level over the row's measured values under the recipe's
  trust policy (``with_trust``). Analysis recomputes trust from the status letters with the policy it is given; the
  column is for readers and quick filters.

Canonical column order (``validate_table``/``write_table``): ``step``, ``segment``, each value column followed by its
status column, ``trust``. No other columns are allowed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ValidationError

from b1500_test_agent.analysis.errors import RunFormatError, RunNotFoundError
from b1500_test_agent.config import load_config
from b1500_test_agent.errors import InvalidConfigError, InvalidInputError
from b1500_test_agent.models.analysis import Quantity, TrustLevel, TrustPolicy, Unit
from b1500_test_agent.models.run import RunManifest
from b1500_test_agent.paths import Paths

STEP = "step"
TRUST = "trust"
SEGMENT = "segment"
STATUS_SUFFIX = "_status"
SEGMENTS: tuple[Literal["fwd", "rev"], ...] = ("fwd", "rev")
TRUST_LEVELS: tuple[TrustLevel, ...] = ("ok", "limited", "untrusted")
QUANTITY_UNITS: dict[str, Unit] = {"V": "V", "I": "A"}
"""Quantity suffix of a value column → unit."""

MANIFEST_FILE = "manifest.json"
DATA_FILE = "data.csv"
INDEX_FILE = "index.jsonl"
CSV_ENCODING = "utf-8"

Segment = Literal["fwd", "rev"]

_VALUE_RE = re.compile(r"^(?P<role>[a-z][a-z0-9_]{0,63})_(?P<qty>[VI])$")
_STATUS_RE = re.compile(r"^[A-Z]$")
_RUN_ID_RE = re.compile(r"^[SH](?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})T\d{6}Z-[0-9a-f]{4}$")
_RANK = {level: rank for rank, level in enumerate(TRUST_LEVELS)}


# -- Column names ----------------------------------------------------------------------------------------------------


def value_column(role: str, qty: str) -> str:
    """Name of the value column of ``role`` and quantity ``qty`` (``V`` or ``I``), e.g. ``drain_I``."""
    name = f"{role}_{qty}"
    if not _VALUE_RE.match(name):
        raise InvalidInputError(f"{name!r} is not a valid value column (role identifier + _V or _I).")
    return name


def status_column(column: str) -> str:
    """Name of the status column that belongs to value column ``column``."""
    return column + STATUS_SUFFIX


def parse_value_column(name: str) -> tuple[str, str] | None:
    """``(role, qty)`` of a value column name, or ``None`` when ``name`` is not one."""
    match = _VALUE_RE.match(name)
    return (match["role"], match["qty"]) if match else None


def column_unit(column: str) -> Unit:
    """Unit of a value column (``V`` for ``*_V``, ``A`` for ``*_I``)."""
    parsed = parse_value_column(column)
    if parsed is None:
        raise InvalidInputError(f"{column!r} is not a value column.")
    return QUANTITY_UNITS[parsed[1]]


def measured_columns(table: pd.DataFrame) -> list[str]:
    """Value columns that have a status column (measured values), in table order."""
    names = set(table.columns)
    return [c for c in table.columns if parse_value_column(c) and status_column(c) in names]


def source_columns(table: pd.DataFrame) -> list[str]:
    """Value columns without a status column (programmed source values), in table order."""
    names = set(table.columns)
    return [c for c in table.columns if parse_value_column(c) and status_column(c) not in names]


# -- Trust -----------------------------------------------------------------------------------------------------------


def _status_ranks(statuses: pd.Series, policy: TrustPolicy) -> np.ndarray:
    mapping = {letter: _RANK[policy.classify(str(letter))] for letter in statuses.unique()}
    return statuses.map(mapping).to_numpy(dtype=int)


def trust_levels(
    table: pd.DataFrame, policy: TrustPolicy | None = None, *, columns: Sequence[str] | None = None
) -> pd.Series:
    """Per-row trust level: the worst level of the row's measured values under ``policy`` (default
    ``TrustPolicy()``). ``columns`` restricts the measured value columns considered."""
    policy = policy if policy is not None else TrustPolicy()
    measured = measured_columns(table)
    if columns is not None:
        unknown = sorted(set(columns) - set(measured))
        if unknown:
            raise InvalidInputError(f"{unknown} are not measured columns; measured: {measured}.")
        measured = [c for c in measured if c in set(columns)]
    ranks = np.zeros(len(table), dtype=int)
    for column in measured:
        ranks = np.maximum(ranks, _status_ranks(table[status_column(column)], policy))
    return pd.Series([TRUST_LEVELS[r] for r in ranks], index=table.index, name=TRUST, dtype=object)


def with_trust(table: pd.DataFrame, policy: TrustPolicy | None = None) -> pd.DataFrame:
    """A copy of ``table`` whose ``trust`` column is computed from its status columns under ``policy``."""
    out = table.copy()
    out[TRUST] = trust_levels(out, policy)
    return out


def row_reasons(table: pd.DataFrame, policy: TrustPolicy | None = None) -> pd.Series:
    """Per-row status letter that decides the row's trust: ``N`` for ok rows, else the letter of the worst class
    among the row's measured values (ties: alphabetical, so ``C`` before ``T``)."""
    policy = policy if policy is not None else TrustPolicy()
    measured = measured_columns(table)
    best_rank = np.zeros(len(table), dtype=int)
    best_letter = np.full(len(table), "N", dtype=object)
    for column in measured:
        letters = table[status_column(column)].astype(str).to_numpy(dtype=object)
        ranks = _status_ranks(table[status_column(column)], policy)
        better = (ranks > best_rank) | ((ranks == best_rank) & (ranks > 0) & (letters < best_letter))
        best_rank = np.where(better, ranks, best_rank)
        best_letter = np.where(better, letters, best_letter)
    return pd.Series(best_letter, index=table.index, name="reason", dtype=object)


# -- Table validation and CSV ----------------------------------------------------------------------------------------


def _as_numbers(series: pd.Series, column: str) -> pd.Series:
    values = series if pd.api.types.is_numeric_dtype(series) else series.mask(series.astype(str) == "")
    try:
        return pd.to_numeric(values, errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise RunFormatError(f"Column {column!r} holds a non-numeric value: {exc}") from exc


def validate_table(table: pd.DataFrame) -> pd.DataFrame:
    """Check ``table`` against the ``data.csv`` contract and return a normalized copy (canonical column order,
    ``step`` as int, values as float, status/trust/segment as str). Raises ``RunFormatError``."""
    columns = [str(c) for c in table.columns]
    if len(set(columns)) != len(columns):
        raise RunFormatError("data.csv has duplicate column names.")
    for required in (STEP, TRUST):
        if required not in columns:
            raise RunFormatError(f"data.csv has no {required!r} column.")
    values = [c for c in columns if parse_value_column(c)]
    allowed = {STEP, TRUST, SEGMENT, *values, *(status_column(v) for v in values)}
    unknown = [c for c in columns if c not in allowed]
    if unknown:
        raise RunFormatError(
            f"data.csv has columns outside the contract: {unknown} (allowed: step, segment, trust, "
            "<role>_V|I and <role>_V|I_status)."
        )
    if not values:
        raise RunFormatError("data.csv has no <role>_V or <role>_I value column.")

    out = pd.DataFrame(index=pd.RangeIndex(len(table)))
    steps = _as_numbers(table[STEP].reset_index(drop=True), STEP)
    if steps.isna().any() or not np.all(np.mod(steps, 1) == 0):
        raise RunFormatError("step must hold integers in every row.")
    out[STEP] = steps.astype("int64")
    if len(out) > 1 and not bool(np.all(np.diff(out[STEP].to_numpy()) > 0)):
        raise RunFormatError("step must be strictly increasing (acquisition order).")
    if SEGMENT in columns:
        segments = table[SEGMENT].reset_index(drop=True).astype(str)
        bad = sorted(set(segments) - set(SEGMENTS))
        if bad:
            raise RunFormatError(f"segment must be one of {list(SEGMENTS)}; found {bad}.")
        out[SEGMENT] = segments.astype(object)
    for column in values:
        out[column] = _as_numbers(table[column].reset_index(drop=True), column)
        status = status_column(column)
        if status in columns:
            letters = table[status].reset_index(drop=True).astype(str)
            bad = sorted({s for s in letters.unique() if not _STATUS_RE.match(s)})
            if bad:
                raise RunFormatError(f"{status} must hold one upper-case status letter per row; found {bad[:5]}.")
            out[status] = letters.astype(object)
    trust = table[TRUST].reset_index(drop=True).astype(str)
    bad = sorted(set(trust) - set(TRUST_LEVELS))
    if bad:
        raise RunFormatError(f"trust must be one of {list(TRUST_LEVELS)}; found {bad}.")
    out[TRUST] = trust.astype(object)
    return out


def write_table(table: pd.DataFrame, path: Path) -> Path:
    """Validate ``table`` and write it as ``data.csv`` (UTF-8, ``newline=""``, ``\\n`` line ends)."""
    tidy = validate_table(table)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as handle:
        tidy.to_csv(handle, index=False, lineterminator="\n")
    return path


def read_table(path: Path) -> pd.DataFrame:
    """Read and validate a ``data.csv``. Raises ``RunFormatError``."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise RunFormatError(f"Cannot read {path.name}: {exc}") from exc
    return validate_table(raw)


# -- Run lookup ------------------------------------------------------------------------------------------------------


def check_run_id(run_id: str) -> str:
    """Return ``run_id`` if it is a well-formed archive run id; raises ``InvalidInputError`` otherwise."""
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        raise InvalidInputError(
            f"{run_id!r} is not a run id (S|H + UTC YYYYMMDDThhmmssZ + '-' + 4 hex, e.g. S20261117T063012Z-7f3a)."
        )
    return run_id


def run_relpath(run_id: str) -> PurePosixPath:
    """Run folder relative to ``<data_root>/runs``: ``<yyyy>/<mm>/<dd>/<run_id>`` (also the index ``path`` value)."""
    match = _RUN_ID_RE.match(check_run_id(run_id))
    assert match is not None
    return PurePosixPath(match["y"], match["m"], match["d"], run_id)


def default_paths() -> Paths:
    """Effective runtime paths: environment overrides plus ``settings.paths`` when the configuration validates;
    the environment/default paths otherwise (analysis must work while the config is broken)."""
    paths = Paths.from_env()
    try:
        return load_config(paths).paths
    except InvalidConfigError:
        return paths


def _runs_dir(data_root: Path | str | None) -> Path:
    return Path(data_root) / "runs" if data_root is not None else default_paths().runs_dir


def _index_lookup(runs_dir: Path, run_id: str) -> Path | None:
    index = runs_dir / INDEX_FILE
    if not index.is_file():
        return None
    for line in reversed(index.read_text(encoding="utf-8").splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("run_id") != run_id or not isinstance(entry.get("path"), str):
            continue
        rel = PurePosixPath(entry["path"])
        if rel.is_absolute() or ".." in rel.parts or ":" in entry["path"]:
            continue
        candidate = runs_dir.joinpath(*rel.parts)
        if (candidate / MANIFEST_FILE).is_file():
            return candidate
    return None


def find_run(run_id: str, *, data_root: Path | str | None = None) -> Path:
    """The run folder of ``run_id``: ``runs/<yyyy>/<mm>/<dd>/<run_id>`` or, failing that, the ``runs/index.jsonl``
    entry. ``data_root`` defaults to ``default_paths().data_root``. Raises ``RunNotFoundError``."""
    runs_dir = _runs_dir(data_root)
    derived = runs_dir.joinpath(*run_relpath(run_id).parts)
    if (derived / MANIFEST_FILE).is_file():
        return derived
    found = _index_lookup(runs_dir, run_id)
    if found is not None:
        return found
    raise RunNotFoundError(
        f"Run {run_id} not found: no {MANIFEST_FILE} in {derived.as_posix()} and no matching entry in "
        f"{(runs_dir / INDEX_FILE).as_posix()}."
    )


def load_manifest(run_dir: Path) -> RunManifest:
    """Read and validate ``<run_dir>/manifest.json``. Raises ``RunFormatError``."""
    path = run_dir / MANIFEST_FILE
    try:
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RunFormatError(f"Cannot read {path.as_posix()}: {exc}") from exc
    except ValidationError as exc:
        raise RunFormatError(f"{path.as_posix()} does not validate as a run manifest: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- RunData ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class RunData:
    """One archived run: its manifest and its tidy table (validated against the ``data.csv`` contract on
    construction). Measured columns are never modified; derived values come back as new objects."""

    manifest: RunManifest
    table: pd.DataFrame = field(repr=False)
    path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "table", validate_table(self.table))

    def __repr__(self) -> str:
        return f"RunData(run_id={self.run_id!r}, points={len(self.table)}, columns={list(self.table.columns)})"

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    @property
    def measured_columns(self) -> list[str]:
        """Value columns with a status column."""
        return measured_columns(self.table)

    @property
    def source_columns(self) -> list[str]:
        """Value columns without a status column (programmed source values)."""
        return source_columns(self.table)

    @property
    def has_segments(self) -> bool:
        """True for double sweeps (a ``segment`` column exists)."""
        return SEGMENT in self.table.columns

    def unit(self, column: str) -> Unit:
        """Unit of a value column of this run; raises ``InvalidInputError`` for an unknown column."""
        if column not in self.table.columns or parse_value_column(column) is None:
            raise InvalidInputError(
                f"Run {self.run_id} has no value column {column!r}; value columns: "
                f"{[c for c in self.table.columns if parse_value_column(c)]}."
            )
        return column_unit(column)

    def param(self, name: str) -> Quantity | None:
        """A resolved plan parameter of this run (``manifest.plan.resolved_params``), or ``None``."""
        return self.manifest.plan.resolved_params.get(name)

    def rows(self, segment: Segment | None = None) -> pd.DataFrame:
        """Rows of one sweep segment in acquisition order (all rows for ``None``). A single sweep has only ``fwd``;
        asking it for ``rev`` raises ``InvalidInputError``."""
        if segment is None:
            return self.table
        if not self.has_segments:
            if segment == "fwd":
                return self.table
            raise InvalidInputError(f"Run {self.run_id} is a single sweep; it has no 'rev' segment.")
        return self.table[self.table[SEGMENT] == segment]

    def segments(self) -> list[Segment | None]:
        """Segments present in acquisition order (``[None]`` for a single sweep)."""
        if not self.has_segments:
            return [None]
        return [s for s in SEGMENTS if s in set(self.table[SEGMENT])]

    def trust_levels(self, policy: TrustPolicy | None = None, *, columns: Sequence[str] | None = None) -> pd.Series:
        """Per-row trust recomputed from the status letters (see module ``trust_levels``)."""
        return trust_levels(self.table, policy, columns=columns)

    def trusted(self, policy: TrustPolicy | None = None, *, columns: Sequence[str] | None = None) -> pd.DataFrame:
        """Rows whose measured values are all ``ok`` under ``policy`` (default ``TrustPolicy()``): limited and
        untrusted rows are dropped, judged per measured column (``columns`` restricts which columns count)."""
        return self.table[self.trust_levels(policy, columns=columns) == "ok"]


def load_run(run_id: str, *, data_root: Path | str | None = None) -> RunData:
    """Load an archived run: find its folder (``find_run``), validate ``manifest.json`` and ``data.csv`` and check
    the data file's sha256 against ``manifest.files`` when listed there. ``data_root`` defaults to the configured
    data root (``default_paths``). Raises ``RunNotFoundError``/``RunFormatError`` (code ``invalid_input``)."""
    run_dir = find_run(run_id, data_root=data_root)
    manifest = load_manifest(run_dir)
    if manifest.run_id != run_id:
        raise RunFormatError(f"{run_dir.as_posix()}/{MANIFEST_FILE} belongs to run {manifest.run_id}, not {run_id}.")
    data_path = run_dir / DATA_FILE
    if not data_path.is_file():
        raise RunFormatError(f"Run {run_id} has no {DATA_FILE} (no measurement table was archived).")
    expected = manifest.files.get(DATA_FILE)
    if expected is not None and _sha256(data_path) != expected:
        raise RunFormatError(f"{DATA_FILE} of run {run_id} does not match the sha256 recorded in its manifest.")
    return RunData(manifest=manifest, table=read_table(data_path), path=run_dir)


def work_dir_for(run_id: str, *, work_root: Path | str | None = None, create: bool = True) -> Path:
    """``<work_dir>/<run_id>/`` for ad-hoc results of agent scripts (record the script path in their
    ``MethodRecord.script``). Run folders are written only by the server; nothing here writes into them."""
    check_run_id(run_id)
    root = Path(work_root) if work_root is not None else default_paths().work_dir
    target = root / run_id
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target
