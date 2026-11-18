"""Run-folder files besides the table and the manifest (blueprint v2 2.6, 2.10): ``progress.json`` and
``partial.csv`` of running (async) runs, ``program.json`` (the pulse/waveform program) and the raw WGFMU blocks
``raw/wgfmu-<ch>-<n>.npz``. Writers are used by the server only (through ``RunFolder``); readers by the service
(``get_run`` on running runs) and by tests. Every file present at finalize is listed with its sha256 in the
manifest.

- ``progress.json``: one ``RunProgress`` (``models/plan.py``), replaced atomically at every checkpoint (temporary
  file + ``os.replace``), so a reader never sees a half-written file; the only run file that is rewritten, and only
  until the run is finalized (the runner writes the final state before ``finalize``).
- ``partial.csv``: the rows acquired so far, appended chunk by chunk in the ``data.csv`` format and column contract
  (``analysis/dataset.py``; ``trust`` computed when the chunk has none). The header comes from the first chunk;
  every later chunk must have the same columns and continue the strictly increasing ``step``. Each chunk is one
  write; a torn last line (a writer killed mid-write) is ignored by ``read_partial`` and cut off by the next
  ``append_partial``. ``data.csv``/``data.npz`` stay the complete table of a finished run.
- ``program.json``: ``RunProgram`` (``models/run.py``), written once.
- ``raw/wgfmu-<ch>-<n>.npz``: exact WGFMU readback of channel ``<ch>`` (``slot*100+1|2``), ``<n>`` = 0, 1, ... per
  channel (three digits), one file per readback the kind chooses to keep (recommended: one per channel and
  execution, the 100,000-point chunks concatenated). ``numpy.savez`` (uncompressed, no pickle) with ``format``,
  ``channel``, ``index``, ``offset`` (index of the first point in the channel's measurement), ``quantity``
  (``V``, ``I`` or empty), ``time_s`` and ``value`` (``float64``, equal length). Never overwritten.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ValidationError

from b1500_test_agent.analysis.dataset import (
    CSV_ENCODING,
    STEP,
    TRUST,
    table_csv,
    validate_table,
    with_trust,
)
from b1500_test_agent.analysis.errors import RunFormatError
from b1500_test_agent.errors import InvalidInputError
from b1500_test_agent.models.analysis import TrustPolicy
from b1500_test_agent.models.plan import RunProgress
from b1500_test_agent.models.run import RunProgram
from b1500_test_agent.session.lock import atomic_write_json

PROGRESS_FILE = "progress.json"
PARTIAL_FILE = "partial.csv"
PROGRAM_FILE = "program.json"
RAW_DIR = "raw"
WGFMU_RAW_FORMAT = "b1500-wgfmu-raw"
WgfmuQuantity = Literal["V", "I"]

_WGFMU_RAW_RE = re.compile(r"^wgfmu-(?P<ch>\d{3,4})-(?P<n>\d{3,})\.npz$")
_TAIL_BYTES = 1 << 16
_ID_ATTEMPTS = 1000


# -- progress.json ---------------------------------------------------------------------------------------------------


def write_progress(run_dir: Path, progress: RunProgress) -> Path:
    """Replace ``<run_dir>/progress.json`` atomically with ``progress``."""
    path = Path(run_dir) / PROGRESS_FILE
    atomic_write_json(path, progress.model_dump(mode="json"))
    return path


def read_progress(run_dir: Path) -> RunProgress | None:
    """The run's last progress record, ``None`` when it has none (a synchronous run). Raises ``RunFormatError``."""
    path = Path(run_dir) / PROGRESS_FILE
    if not path.is_file():
        return None
    try:
        return RunProgress.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RunFormatError(f"{PROGRESS_FILE} of {Path(run_dir).name} is unreadable: {exc}") from exc


# -- partial.csv -----------------------------------------------------------------------------------------------------


def _complete_length(path: Path) -> int:
    """Byte length of ``path`` up to and including its last line end (0 when it has none)."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        position = size
        while position > 0:
            start = max(0, position - _TAIL_BYTES)
            handle.seek(start)
            chunk = handle.read(position - start)
            cut = chunk.rfind(b"\n")
            if cut >= 0:
                return start + cut + 1
            position = start
    return 0


def _header(path: Path) -> list[str]:
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        return handle.readline().rstrip("\n").split(",")


def _last_step(path: Path, length: int) -> int | None:
    """``step`` of the last complete data line (``None`` when only the header is there)."""
    start = max(0, length - _TAIL_BYTES)
    with path.open("rb") as handle:
        handle.seek(start)
        lines = handle.read(length - start).decode(CSV_ENCODING, errors="replace").splitlines()
    if len(lines) < 2 and start == 0:
        return None  # header only
    try:
        return int(lines[-1].split(",", 1)[0])
    except (IndexError, ValueError) as exc:
        raise RunFormatError(f"{path.name}: cannot read the step of its last line") from exc


def append_partial(run_dir: Path, rows: pd.DataFrame, policy: TrustPolicy | None = None) -> int:
    """Append ``rows`` (data-table columns; ``trust`` is computed under ``policy`` when missing) to
    ``<run_dir>/partial.csv`` and return the number of rows appended. Raises ``RunFormatError`` when the columns
    differ from the file's header or ``step`` does not continue."""
    tidy = validate_table(rows if TRUST in rows.columns else with_trust(rows, policy))
    path = Path(run_dir) / PARTIAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    length = _complete_length(path) if path.is_file() else 0
    if path.is_file() and length != path.stat().st_size:
        with path.open("r+b") as handle:  # cut a torn last line (a writer killed mid-write)
            handle.truncate(length)
    header = length > 0
    if header:
        columns = _header(path)
        if columns != list(tidy.columns):
            raise RunFormatError(f"{PARTIAL_FILE} has columns {columns}; the new rows have {list(tidy.columns)}.")
        last = _last_step(path, length)
        if last is not None and len(tidy) and int(tidy[STEP].iloc[0]) <= last:
            raise RunFormatError(f"{PARTIAL_FILE}: step must continue after {last}; the new rows start at "
                                 f"{int(tidy[STEP].iloc[0])}.")
    text = table_csv(tidy, header=not header)
    with path.open("a", encoding=CSV_ENCODING, newline="") as handle:
        handle.write(text)
    return len(tidy)


def read_partial(run_dir: Path) -> pd.DataFrame | None:
    """The rows of ``<run_dir>/partial.csv`` (validated; a torn last line is ignored), ``None`` without the file.
    Raises ``RunFormatError``."""
    path = Path(run_dir) / PARTIAL_FILE
    if not path.is_file():
        return None
    length = _complete_length(path)
    if length == 0:
        return None
    with path.open("rb") as handle:
        data = handle.read(length)
    try:
        raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (ValueError, pd.errors.ParserError) as exc:
        raise RunFormatError(f"Cannot read {PARTIAL_FILE}: {exc}") from exc
    return validate_table(raw)


# -- program.json ----------------------------------------------------------------------------------------------------


def write_program(run_dir: Path, program: RunProgram) -> Path:
    """Write ``<run_dir>/program.json`` once (``FileExistsError`` when it exists)."""
    path = Path(run_dir) / PROGRAM_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(program.model_dump_json(indent=1) + "\n")
    return path


def read_program(run_dir: Path) -> RunProgram | None:
    """The run's ``program.json``, ``None`` when it has none. Raises ``RunFormatError``."""
    path = Path(run_dir) / PROGRAM_FILE
    if not path.is_file():
        return None
    try:
        return RunProgram.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RunFormatError(f"{PROGRAM_FILE} of {Path(run_dir).name} is unreadable: {exc}") from exc


# -- raw/wgfmu-<ch>-<n>.npz ------------------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class WgfmuRaw:
    """One raw WGFMU readback block (see the module docstring)."""

    channel: int
    index: int
    offset: int
    quantity: WgfmuQuantity | None
    time_s: np.ndarray
    value: np.ndarray

    def __len__(self) -> int:
        return int(self.value.shape[0])


def check_wgfmu_channel(channel: int) -> int:
    """``channel`` if it is a WGFMU channel number (``slot*100+1`` or ``+2``, slot 1-10; PG Table 4-1)."""
    if isinstance(channel, bool) or not isinstance(channel, int | np.integer) or not (
            1 <= int(channel) // 100 <= 10 and int(channel) % 100 in (1, 2)):
        raise InvalidInputError(f"{channel!r} is not a WGFMU channel (slot*100 + 1 or 2, e.g. 201).")
    return int(channel)


def wgfmu_raw_name(channel: int, index: int) -> str:
    """File name of raw block ``index`` of ``channel``: ``wgfmu-<ch>-<nnn>.npz``."""
    if index < 0:
        raise InvalidInputError("a raw block index is 0 or more")
    return f"wgfmu-{check_wgfmu_channel(channel)}-{index:03d}.npz"


def wgfmu_raw_files(run_dir: Path, channel: int | None = None) -> list[Path]:
    """The raw WGFMU block files of a run, ordered by channel and index (only ``channel`` when given)."""
    directory = Path(run_dir) / RAW_DIR
    if not directory.is_dir():
        return []
    found = []
    for path in directory.iterdir():
        match = _WGFMU_RAW_RE.match(path.name)
        if match and path.is_file() and (channel is None or int(match["ch"]) == channel):
            found.append((int(match["ch"]), int(match["n"]), path))
    return [path for _, _, path in sorted(found)]


def write_wgfmu_raw(run_dir: Path, channel: int, time_s: np.ndarray, value: np.ndarray, *, offset: int = 0,
                    quantity: WgfmuQuantity | None = None) -> str:
    """Store one raw WGFMU readback block of ``channel`` as the next ``raw/wgfmu-<ch>-<n>.npz`` and return its
    run-relative path. ``time_s``/``value`` are 1-D arrays of equal length (stored as ``float64``)."""
    check_wgfmu_channel(channel)
    times = np.asarray(time_s, dtype=np.float64)
    values = np.asarray(value, dtype=np.float64)
    if times.ndim != 1 or values.ndim != 1 or times.shape != values.shape:
        raise InvalidInputError(f"time_s and value must be 1-D arrays of equal length; got {times.shape} and "
                                f"{values.shape}.")
    if isinstance(offset, bool) or int(offset) != offset or offset < 0:
        raise InvalidInputError("offset must be an integer >= 0")
    if quantity not in (None, "V", "I"):
        raise InvalidInputError(f"quantity must be 'V', 'I' or None, not {quantity!r}")
    directory = Path(run_dir) / RAW_DIR
    directory.mkdir(parents=True, exist_ok=True)
    index = len(wgfmu_raw_files(run_dir, channel))
    for _ in range(_ID_ATTEMPTS):
        name = wgfmu_raw_name(channel, index)
        try:
            with (directory / name).open("xb") as handle:
                np.savez(handle, format=np.asarray(WGFMU_RAW_FORMAT), channel=np.int64(channel),
                         index=np.int64(index), offset=np.int64(offset), quantity=np.asarray(quantity or ""),
                         time_s=times, value=values)
            return f"{RAW_DIR}/{name}"
        except FileExistsError:
            index += 1
    raise FileExistsError(f"no free raw WGFMU file name for channel {channel} in {directory.as_posix()}")


def read_wgfmu_raw(path: Path) -> WgfmuRaw:
    """Read one raw WGFMU block file. Raises ``RunFormatError``."""
    try:
        with np.load(path, allow_pickle=False) as archive:
            if str(archive["format"]) != WGFMU_RAW_FORMAT:
                raise RunFormatError(f"{Path(path).name} is not a {WGFMU_RAW_FORMAT} file.")
            quantity = str(archive["quantity"]) or None
            raw = WgfmuRaw(channel=int(archive["channel"]), index=int(archive["index"]),
                           offset=int(archive["offset"]), quantity=quantity,  # type: ignore[arg-type]
                           time_s=archive["time_s"], value=archive["value"])
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
        raise RunFormatError(f"Cannot read {Path(path).name}: {exc}") from exc
    if raw.time_s.shape != raw.value.shape or raw.value.ndim != 1:
        raise RunFormatError(f"{Path(path).name}: time_s and value differ in shape.")
    return raw
