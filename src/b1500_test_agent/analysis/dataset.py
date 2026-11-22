"""Run datasets: the run-table contract (``data.csv`` / ``data.npz``), run lookup and ``RunData`` (blueprint v1 2.7,
2.8; v2 2.10).

This module is the single definition of the run-table contract; the archive (``archive/store.py``) builds tables
with ``with_trust``, writes them with ``write_run_table`` and places run folders at ``run_relpath``.

**Run folder.** ``<data_root>/runs/<yyyy>/<mm>/<dd>/<run_id>/`` with ``manifest.json`` (``RunManifest``) and the run
table: ``data.csv`` for at most ``CSV_MAX_ROWS`` (200,000) rows, otherwise ``data.npz`` plus ``preview.csv`` (at most
``PREVIEW_MAX_ROWS`` = 2,000 evenly spaced rows, first and last kept, same CSV format). Exactly one of ``data.csv``
and ``data.npz`` exists. The date folders come from the run id (``S|H`` + UTC ``YYYYMMDDThhmmssZ`` + ``-`` + 4 hex).
``runs/index.jsonl`` holds one JSON object per finalized run with at least ``run_id`` and ``path`` (the run folder
relative to ``runs/``, POSIX separators, e.g. ``2026/11/17/S20261117T063012Z-7f3a``); ``load_run`` falls back to it
when the derived folder has no manifest.

**Columns** (one row per measurement point in acquisition order):

- ``step`` (required): 0-based point index in acquisition order; integers, strictly increasing.
- ``<role>_<qty>``: a value of recipe role ``<role>`` (lower-case identifier, may contain ``_``). ``<qty>`` and unit:
  ``V`` (V), ``I`` (A); MFCMU quantities by the IMP model ``Cp`` (F), ``G`` (S), ``Cs`` (F), ``Rs`` (Ohm), ``D`` (1),
  ``Z`` (Ohm), ``theta`` (rad). With a status column it is a measured value; a ``V``/``I`` column without one is the
  programmed source value (e.g. ``gate_V`` of a swept gate whose voltage is not measured); MFCMU quantities are
  always measured. WGFMU points use ``<role>_V``/``<role>_I`` like SMU points. Empty cells are missing values; the
  invalid-data value ``199.999E+99`` is kept as read.
- ``<role>_<qty>_status``: the single-letter status of that value (``N`` normal, ``C``/``T`` compliance,
  ``V X F D G S U`` invalid; any other letter is untrusted), exactly one upper-case letter. WGFMU flags map to
  letters (range overflow ``V``, error ``X``).
- ``trust`` (required): ``ok``, ``limited`` or ``untrusted``: the worst level over the row's measured values under
  the recipe's trust policy (``with_trust``). Analysis recomputes trust from the status letters with the policy it
  is given; the column is for readers and quick filters.
- Optional context columns (programmed or time-base values; never measured values):
  ``t_s`` time in seconds since the run's time origin (finite, >= 0, or empty); ``cycle`` 0-based cycle index
  (integer >= 0 in every row); ``segment`` sweep branch ``fwd``/``rev`` of a double sweep (every row); ``phase`` one
  of ``stress read program erase recovery correction`` (every row); ``event`` WGFMU measure-event name and
  ``range`` / ``<role>_range`` measurement-range label (``range`` when one channel's range is recorded,
  ``<role>_range`` per role; tokens of letters, digits, ``_ . + -``, at most 32 characters, or empty);
  ``freq_hz`` MFCMU frequency (> 0 or empty), ``ac_vrms`` AC level (>= 0 or empty), ``dc_v`` DC bias (finite or
  empty).

Canonical column order (``validate_table``): ``step``, ``t_s``, ``cycle``, ``segment``, ``phase``, ``event``,
``freq_hz``, ``ac_vrms``, ``dc_v``, ``range``, the ``<role>_range`` columns, each value column (input order) followed
by its status column, ``trust``. No other columns are allowed, and a table needs at least one value column. A v1
table (``step``, ``segment``, ``V``/``I`` values, ``trust``) keeps its v1 bytes.

**CSV files** (``data.csv``, ``preview.csv``, ``partial.csv``): UTF-8 without BOM, ``\\n`` line ends, written with
``newline=""``, one header row, floats in Python's shortest round-trip form.

**data.npz** (``numpy.savez``, uncompressed: a 4 M-point table loads in well under a second; floats compress poorly):
``schema`` = JSON text ``{"format": "b1500-run-table", "version": 1, "rows": n, "columns": [...]}`` (canonical
order); ``col.<name>`` = the column's values (``int64`` for ``step``/``cycle``, ``float64`` for numbers, an unsigned
integer code array for text columns); ``lev.<name>`` = the levels of a text column (``codes`` index them). Read it
with ``read_table`` (no pickle).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

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
T_S = "t_s"
CYCLE = "cycle"
PHASE = "phase"
EVENT = "event"
RANGE = "range"
FREQ_HZ = "freq_hz"
AC_VRMS = "ac_vrms"
DC_V = "dc_v"
STATUS_SUFFIX = "_status"
RANGE_SUFFIX = "_range"
SEGMENTS: tuple[Literal["fwd", "rev"], ...] = ("fwd", "rev")
PHASES: tuple[str, ...] = ("stress", "read", "program", "erase", "recovery", "correction")
TRUST_LEVELS: tuple[TrustLevel, ...] = ("ok", "limited", "untrusted")
QUANTITY_UNITS: dict[str, Unit] = {
    "V": "V", "I": "A", "Cp": "F", "G": "S", "Cs": "F", "Rs": "Ohm", "D": "1", "Z": "Ohm", "theta": "rad",
}  # fmt: skip
"""Quantity suffix of a value column → unit."""
SOURCE_QUANTITIES = frozenset({"V", "I"})
"""Quantities whose column may hold a programmed source value (no status column)."""
CONTEXT_COLUMNS: tuple[str, ...] = (T_S, CYCLE, SEGMENT, PHASE, EVENT, FREQ_HZ, AC_VRMS, DC_V, RANGE)
"""Optional context columns in canonical order (the ``<role>_range`` columns follow ``range``)."""

MANIFEST_FILE = "manifest.json"
DATA_FILE = "data.csv"
NPZ_FILE = "data.npz"
PREVIEW_FILE = "preview.csv"
INDEX_FILE = "index.jsonl"
CSV_ENCODING = "utf-8"
CSV_MAX_ROWS = 200_000
"""Largest table archived as ``data.csv``; larger tables go to ``data.npz`` + ``preview.csv``."""
PREVIEW_MAX_ROWS = 2_000
NPZ_FORMAT = "b1500-run-table"
NPZ_VERSION = 1

Segment = Literal["fwd", "rev"]

_QTY = "|".join(sorted(QUANTITY_UNITS, key=len, reverse=True))
_VALUE_RE = re.compile(rf"^(?P<role>[a-z][a-z0-9_]{{0,63}})_(?P<qty>{_QTY})$")
_ROLE_RANGE_RE = re.compile(r"^(?P<role>[a-z][a-z0-9_]{0,63})_range$")
_STATUS_RE = re.compile(r"^[A-Z]$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,32}$")
_RUN_ID_RE = re.compile(r"^[SH](?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})T\d{6}Z-[0-9a-f]{4}$")
_RANK = {level: rank for rank, level in enumerate(TRUST_LEVELS)}
_TRUST_NAMES = np.asarray(TRUST_LEVELS, dtype=object)
_INT_COLUMNS = frozenset({STEP, CYCLE})


# -- Column names ----------------------------------------------------------------------------------------------------


def value_column(role: str, qty: str) -> str:
    """Name of the value column of ``role`` and quantity ``qty`` (``V``, ``I`` or an MFCMU quantity), e.g.
    ``drain_I``."""
    name = f"{role}_{qty}"
    if not _VALUE_RE.match(name):
        raise InvalidInputError(f"{name!r} is not a valid value column (role identifier + _<qty>, qty in "
                                f"{list(QUANTITY_UNITS)}).")
    return name


def status_column(column: str) -> str:
    """Name of the status column that belongs to value column ``column``."""
    return column + STATUS_SUFFIX


def range_column(role: str) -> str:
    """Name of the per-role range-label column of ``role``, e.g. ``drain_range``."""
    name = role + RANGE_SUFFIX
    if not _ROLE_RANGE_RE.match(name):
        raise InvalidInputError(f"{role!r} is not a role identifier.")
    return name


def parse_value_column(name: str) -> tuple[str, str] | None:
    """``(role, qty)`` of a value column name, or ``None`` when ``name`` is not one."""
    match = _VALUE_RE.match(name)
    return (match["role"], match["qty"]) if match else None


def column_unit(column: str) -> Unit:
    """Unit of a value column (``V`` for ``*_V``, ``A`` for ``*_I``, ``F`` for ``*_Cp`` ...)."""
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
    return pd.Series(_TRUST_NAMES[ranks], index=table.index, name=TRUST, dtype=object)


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


# -- Table validation ------------------------------------------------------------------------------------------------


def _as_numbers(series: pd.Series, column: str) -> pd.Series:
    values = series if pd.api.types.is_numeric_dtype(series) else series.mask(series.astype(str) == "")
    try:
        return pd.to_numeric(values, errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise RunFormatError(f"Column {column!r} holds a non-numeric value: {exc}") from exc


def _as_text(series: pd.Series) -> pd.Series:
    """Text cells as ``str`` (missing values → empty string, as a CSV round trip gives them)."""
    return series.astype(object).where(series.notna(), "").astype(str).astype(object)


def _integers(series: pd.Series, column: str, *, minimum: int | None = None) -> pd.Series:
    numbers = _as_numbers(series, column)
    if numbers.isna().any() or not np.all(np.mod(numbers, 1) == 0):
        raise RunFormatError(f"{column} must hold integers in every row.")
    if minimum is not None and len(numbers) and float(numbers.min()) < minimum:
        raise RunFormatError(f"{column} must be at least {minimum} in every row.")
    return numbers.astype("int64")


def _bounded(series: pd.Series, column: str, *, low: float | None = None, strict: bool = False) -> pd.Series:
    """Numbers that are finite where present (empty allowed) and above ``low`` (``strict``: > instead of >=)."""
    numbers = _as_numbers(series, column)
    present = numbers.dropna()
    if not np.all(np.isfinite(present)):
        raise RunFormatError(f"{column} must hold finite numbers or empty cells.")
    if low is not None and len(present):
        bad = present <= low if strict else present < low
        if bool(bad.any()):
            raise RunFormatError(f"{column} must be {'>' if strict else '>='} {low:g} where given; found "
                                 f"{float(present[bad].iloc[0])!r}.")
    return numbers


def _vocabulary(series: pd.Series, column: str, allowed: Sequence[str]) -> pd.Series:
    text = _as_text(series)
    bad = sorted(set(text.unique()) - set(allowed))
    if bad:
        raise RunFormatError(f"{column} must be one of {list(allowed)}; found {bad[:5]}.")
    return text


def _tokens(series: pd.Series, column: str) -> pd.Series:
    text = _as_text(series)
    bad = sorted(s for s in text.unique() if s and not _TOKEN_RE.match(s))
    if bad:
        raise RunFormatError(f"{column} must hold labels of letters, digits, '_', '.', '+' or '-' (at most 32 "
                             f"characters) or empty cells; found {bad[:5]}.")
    return text


def _context(column: str, series: pd.Series) -> pd.Series:
    """Validated values of one optional context column."""
    if column == T_S:
        return _bounded(series, column, low=0.0)
    if column == CYCLE:
        return _integers(series, column, minimum=0)
    if column == SEGMENT:
        return _vocabulary(series, column, SEGMENTS)
    if column == PHASE:
        return _vocabulary(series, column, PHASES)
    if column == FREQ_HZ:
        return _bounded(series, column, low=0.0, strict=True)
    if column == AC_VRMS:
        return _bounded(series, column, low=0.0)
    if column == DC_V:
        return _bounded(series, column)
    return _tokens(series, column)  # event, range, <role>_range


def validate_table(table: pd.DataFrame) -> pd.DataFrame:
    """Check ``table`` against the run-table contract and return a normalized copy (canonical column order,
    ``step``/``cycle`` as int, numbers as float, text columns as str). Raises ``RunFormatError``."""
    columns = [str(c) for c in table.columns]
    if len(set(columns)) != len(columns):
        raise RunFormatError("data.csv has duplicate column names.")
    for required in (STEP, TRUST):
        if required not in columns:
            raise RunFormatError(f"data.csv has no {required!r} column.")
    values = [c for c in columns if parse_value_column(c)]
    role_ranges = [c for c in columns if _ROLE_RANGE_RE.match(c)]
    allowed = {STEP, TRUST, *CONTEXT_COLUMNS, *role_ranges, *values, *(status_column(v) for v in values)}
    unknown = [c for c in columns if c not in allowed]
    if unknown:
        raise RunFormatError(
            f"data.csv has columns outside the contract: {unknown} (allowed: step, trust, "
            f"{', '.join(CONTEXT_COLUMNS)}, <role>_range, <role>_<qty> with qty in {list(QUANTITY_UNITS)} and "
            "<role>_<qty>_status)."
        )
    if not values:
        raise RunFormatError("data.csv has no value column (<role>_V, <role>_I or an MFCMU quantity).")
    quantities = {v: v.rsplit("_", 1)[1] for v in values}
    unmeasured = [v for v in values if quantities[v] not in SOURCE_QUANTITIES and status_column(v) not in columns]
    if unmeasured:
        raise RunFormatError(f"MFCMU quantity columns are always measured; {unmeasured} lack a status column.")

    data = table.copy(deep=False)
    data.columns = columns
    data = data.reset_index(drop=True)
    out: dict[str, Any] = {STEP: _integers(data[STEP], STEP)}
    steps = out[STEP].to_numpy()
    if len(steps) > 1 and not bool(np.all(np.diff(steps) > 0)):
        raise RunFormatError("step must be strictly increasing (acquisition order).")
    for column in (*CONTEXT_COLUMNS, *role_ranges):
        if column in columns:
            out[column] = _context(column, data[column])
    for column in values:
        out[column] = _as_numbers(data[column], column)
        status = status_column(column)
        if status in columns:
            letters = _as_text(data[status])
            bad = sorted({s for s in letters.unique() if not _STATUS_RE.match(s)})
            if bad:
                raise RunFormatError(f"{status} must hold one upper-case status letter per row; found {bad[:5]}.")
            out[status] = letters
    out[TRUST] = _vocabulary(data[TRUST], TRUST, TRUST_LEVELS)
    return pd.DataFrame(out, index=pd.RangeIndex(len(data)))


# -- CSV and npz files -----------------------------------------------------------------------------------------------


def table_csv(table: pd.DataFrame, *, header: bool = True) -> str:
    """CSV text of an already validated table (``\\n`` line ends)."""
    buffer = io.StringIO()
    table.to_csv(buffer, index=False, header=header, lineterminator="\n")
    return buffer.getvalue()


def _write_csv(tidy: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as handle:
        tidy.to_csv(handle, index=False, lineterminator="\n")
    return path


def write_table(table: pd.DataFrame, path: Path) -> Path:
    """Validate ``table`` and write it as CSV at ``path`` (UTF-8, ``newline=""``, ``\\n`` line ends); for any row
    count (``write_run_table`` chooses the archive format)."""
    return _write_csv(validate_table(table), path)


def read_csv_table(path: Path) -> pd.DataFrame:
    """Read and validate a CSV run table (``data.csv``, ``preview.csv``, ``partial.csv``). Raises
    ``RunFormatError``."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise RunFormatError(f"Cannot read {path.name}: {exc}") from exc
    return validate_table(raw)


def write_npz_table(table: pd.DataFrame, path: Path) -> Path:
    """Validate ``table`` and write it as ``data.npz`` (module docstring) at ``path``."""
    return _write_npz(validate_table(table), path)


def _write_npz(tidy: pd.DataFrame, path: Path) -> Path:
    arrays: dict[str, np.ndarray] = {}
    for column in tidy.columns:
        series = tidy[column]
        if pd.api.types.is_numeric_dtype(series):
            arrays[f"col.{column}"] = series.to_numpy(dtype="int64" if column in _INT_COLUMNS else "float64")
        else:
            codes, levels = pd.factorize(series, sort=True)
            arrays[f"col.{column}"] = codes.astype(np.min_scalar_type(max(len(levels) - 1, 0)))
            arrays[f"lev.{column}"] = np.asarray([str(level) for level in levels], dtype=str)
    schema = {"format": NPZ_FORMAT, "version": NPZ_VERSION, "rows": len(tidy), "columns": list(tidy.columns)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez(handle, schema=np.asarray(json.dumps(schema)), **arrays)  # type: ignore[arg-type]
    return path


def _npz_columns(path: Path) -> tuple[int, list[str], dict[str, np.ndarray]]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
        schema = json.loads(str(arrays.pop("schema")))
        rows, columns = int(schema["rows"]), [str(c) for c in schema["columns"]]
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile) as exc:
        raise RunFormatError(f"Cannot read {path.name}: {exc}") from exc
    if schema.get("format") != NPZ_FORMAT or schema.get("version") != NPZ_VERSION:
        raise RunFormatError(f"{path.name} is not a version-{NPZ_VERSION} {NPZ_FORMAT} file.")
    for column in columns:
        values = arrays.get(f"col.{column}")
        if values is None or values.shape != (rows,):
            raise RunFormatError(f"{path.name}: column {column!r} is missing or does not hold {rows} values.")
    return rows, columns, arrays


def _npz_frame(columns: list[str], arrays: dict[str, np.ndarray], rows: np.ndarray | None,
               name: str) -> pd.DataFrame:
    out: dict[str, Any] = {}
    for column in columns:
        values = arrays[f"col.{column}"]
        values = values if rows is None else values[rows]
        levels = arrays.get(f"lev.{column}")
        if levels is not None:
            if values.dtype.kind not in "ui" or (values.size and (int(values.min()) < 0
                                                                   or int(values.max()) >= len(levels))):
                raise RunFormatError(f"{name}: column {column!r} has codes without a level.")
            values = levels.astype(object)[values.astype(np.intp)]
        out[column] = values
    return pd.DataFrame(out)


def read_npz_table(path: Path) -> pd.DataFrame:
    """Read and validate a ``data.npz`` run table. Raises ``RunFormatError``."""
    _, columns, arrays = _npz_columns(path)
    return validate_table(_npz_frame(columns, arrays, None, path.name))


def read_table(path: Path) -> pd.DataFrame:
    """Read and validate a run table: ``.npz`` files as ``data.npz``, anything else as CSV. Raises
    ``RunFormatError``."""
    return read_npz_table(path) if path.suffix == ".npz" else read_csv_table(path)


def sample_indices(n: int, k: int) -> np.ndarray:
    """At most ``k`` evenly spaced row indices of ``n`` rows, first and last included."""
    if n <= k:
        return np.arange(n)
    if k <= 1:
        return np.zeros(min(n, 1), dtype=np.intp)
    return np.unique(np.linspace(0, n - 1, k).round().astype(np.intp))


def read_table_excerpt(path: Path, max_rows: int | None = None) -> tuple[pd.DataFrame, int]:
    """The run table at ``path`` and its row count; with ``max_rows`` only that many evenly spaced rows (first and
    last kept). A ``data.npz`` excerpt validates only the rows it returns (``read_table`` checks every row)."""
    if path.suffix != ".npz":
        table = read_csv_table(path)
        return (table if max_rows is None else table.iloc[sample_indices(len(table), max_rows)]
                .reset_index(drop=True)), len(table)
    rows, columns, arrays = _npz_columns(path)
    picked = None if max_rows is None else sample_indices(rows, max_rows)
    return validate_table(_npz_frame(columns, arrays, picked, path.name)), rows


def write_run_table(table: pd.DataFrame, run_dir: Path) -> Path:
    """Archive ``table`` in ``run_dir``: ``data.csv`` for at most ``CSV_MAX_ROWS`` rows, else ``data.npz`` and
    ``preview.csv`` (``PREVIEW_MAX_ROWS`` evenly spaced rows). Never overwrites; returns the data file's path."""
    tidy = validate_table(table)
    for name in (DATA_FILE, NPZ_FILE, PREVIEW_FILE):
        if (run_dir / name).exists():
            raise FileExistsError(f"{(run_dir / name).as_posix()} already exists")
    if len(tidy) <= CSV_MAX_ROWS:
        return _write_csv(tidy, run_dir / DATA_FILE)
    path = _write_npz(tidy, run_dir / NPZ_FILE)
    _write_csv(tidy.iloc[sample_indices(len(tidy), PREVIEW_MAX_ROWS)], run_dir / PREVIEW_FILE)
    return path


def run_table_path(run_dir: Path) -> Path | None:
    """The run table of ``run_dir`` (``data.csv`` or ``data.npz``), ``None`` when there is none. Raises
    ``RunFormatError`` when both exist."""
    csv, npz = run_dir / DATA_FILE, run_dir / NPZ_FILE
    if csv.is_file() and npz.is_file():
        raise RunFormatError(f"{run_dir.as_posix()} holds both {DATA_FILE} and {NPZ_FILE}; exactly one is allowed.")
    return csv if csv.is_file() else npz if npz.is_file() else None


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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# -- RunData ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class RunData:
    """One archived run: its manifest and its tidy table (validated against the run-table contract on
    construction). Measured columns are never modified; derived values come back as new objects."""

    manifest: RunManifest
    table: pd.DataFrame = field(repr=False)
    path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "table", validate_table(self.table))

    def __repr__(self) -> str:
        return f"RunData(run_id={self.run_id!r}, points={len(self.table)}, columns={list(self.table.columns)})"

    def subset(self, rows: pd.DataFrame) -> RunData:
        """This run restricted to ``rows``, a selection of rows of ``self.table`` in table order (index renumbered).
        Not validated again: rows of a validated table keep its columns, types and increasing ``step``, so
        ``validate_table`` would return the same table (per-read analyses of a long stress run validated every read
        again).

        Raises:
            ValueError: If ``rows`` does not have exactly the columns of ``self.table``.
        """
        if list(rows.columns) != list(self.table.columns):
            raise ValueError("a subset keeps the columns of the run table")
        data = object.__new__(RunData)
        object.__setattr__(data, "manifest", self.manifest)
        object.__setattr__(data, "table", rows.reset_index(drop=True))
        object.__setattr__(data, "path", self.path)
        return data

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
    """Load an archived run: find its folder (``find_run``), validate ``manifest.json`` and the run table
    (``data.csv`` or ``data.npz``) and check the table file's sha256 against ``manifest.files`` when listed there.
    ``data_root`` defaults to the configured data root (``default_paths``). Raises ``RunNotFoundError``/
    ``RunFormatError`` (code ``invalid_input``)."""
    run_dir = find_run(run_id, data_root=data_root)
    manifest = load_manifest(run_dir)
    if manifest.run_id != run_id:
        raise RunFormatError(f"{run_dir.as_posix()}/{MANIFEST_FILE} belongs to run {manifest.run_id}, not {run_id}.")
    data_path = run_table_path(run_dir)
    if data_path is None:
        raise RunFormatError(f"Run {run_id} has no {DATA_FILE} or {NPZ_FILE} (no measurement table was archived).")
    expected = manifest.files.get(data_path.name)
    if expected is not None and _sha256(data_path) != expected:
        raise RunFormatError(f"{data_path.name} of run {run_id} does not match the sha256 recorded in its manifest.")
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
