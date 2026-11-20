"""Persistent simulator state: ``<state_dir>/sim/<scenario>.state.json`` (blueprint 2.7, 3).

The MCP server and the CLI each run their own in-process simulator; they see one instrument because the
persistent part of its state — channel outputs and relays (with ranges and compliance), DUT internal state and the
command log — is loaded right after the instrument lock is acquired and saved right before it is released
(``SimTransport.load_state()`` / ``save_state()``, called by the session in WP1.6). Everything else (buffers,
measurement setup, error queue, active faults) belongs to one process and one transaction.

Writes are atomic: a temporary file in the same directory, then ``os.replace`` (Windows-safe).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STATE_VERSION = 1
COMMAND_LOG_LIMIT = 5000
"""Most recent command records kept in the state file (older ones are counted in ``log_dropped``)."""

Outcome = Literal["ok", "error", "unsupported", "rejected", "queued", "dropped"]
"""What happened to a command: executed (``ok``), failed with an instrument error (``error``), not in the v1 subset
(``unsupported``, error 100), refused because of its line (``rejected``, e.g. ``AB`` combined with other commands),
held in the input buffer behind a hung measurement (``queued``), or never received because of a link fault
(``dropped``)."""


class _Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=False)


class CommandRecord(_Mutable):
    """One entry of the simulator command log (spy and grader source).

    ``line`` is the full line as written; ``command`` the single command; ``source`` marks commands that set an
    output level (``DV``, ``WV``). Interface events use pseudo mnemonics in angle brackets (``<device_clear>``).
    """

    seq: int
    ts: str
    clock_s: float
    line: str
    command: str
    mnemonic: str
    args: list[str] = Field(default_factory=list)
    outcome: Outcome
    error: int | None = None
    source: bool = False


class ChannelState(_Mutable):
    """Output state of one channel. ``mode`` is what it forces: ``V`` (``voltage`` with current compliance ``icomp``,
    V and A) or ``I`` (``current`` with voltage compliance ``vcomp``, A and V; ``voltage`` is then unused and 0). On an
    MFCMU ``voltage`` is the DC bias and ``ac_vrms``/``freq_hz`` the oscillator level and frequency (WP8.1; the
    ``CN``/``CL`` condition is 0 V, 0 V rms, 1 kHz, PG PDF 382)."""

    output_on: bool = False
    mode: Literal["V", "I"] = "V"
    voltage: float = 0.0
    icomp: float | None = None
    current: float = 0.0
    vcomp: float | None = None
    comp_polarity: int = 0
    vrange: int = 0
    irange: int = 0
    ac_vrms: float = 0.0
    freq_hz: float = 1000.0


class CmuCorrectionPoint(_Mutable):
    """Correction data of one listed frequency (``CORRL``): the standards' readings taken by ``CORR?`` (or set by
    ``CORRDT``) as measured impedances ``[re, im]`` in Ohm, and the load standard's reference impedance in use then."""

    freq_hz: float
    open: list[float] | None = None
    short: list[float] | None = None
    load: list[float] | None = None
    load_ref: list[float] | None = None


class CmuPersistent(_Mutable):
    """MFCMU state that survives host sessions (WP8.1): the phase compensation mode (``ADJ``; 0 auto after ``*RST``),
    the correction frequency list (``CORRL``/``CLCORR``), the standards' reference values (``DCORR``: correction mode
    -> ``[mode, primary, secondary]``) and the correction data per listed frequency. Cleared only by a power cycle
    (and the ``cmu_correction_lost`` fault); ``*RST`` keeps the data and switches the corrections off (PG PDF 382,
    388)."""

    adj_mode: int = Field(default=0, ge=0, le=2)
    freqs: list[float] = Field(default_factory=list)
    standards: dict[int, list[float]] = Field(default_factory=dict)
    data: list[CmuCorrectionPoint] = Field(default_factory=list)


class SimPersistentState(_Mutable):
    """Contents of the state file. ``auto_calibration`` is the ``CM`` switch: instrument state that survives host
    sessions until ``*RST``/device clear (PG p379 (4-61)).

    Family state read by the bring-up probe (blueprint v2 7.1; the family work packages add the commands that set
    it): ``selector_mode`` = the ``ERMOD`` control-mode sum, ``selector_ports`` = ``ERSSP`` port -> status 0-3 (a
    missing port is 0, open), ``spgu_output_active`` = ``SPST?``, ``cmu_corrections`` = MFCMU channel -> ``CORRST``
    mode (1 open, 2 short, 3 load) -> ON, ``cmu_phase_results`` = MFCMU channel -> last ``ADJ?`` result (missing =
    3, not performed). ``*RST``/device clear reset all but the phase results (power-on state).

    ASU state (WP7.1; SMU channel -> setting, a missing channel holds the initial setting, PG Table 2-13, PDF 180):
    ``asu_paths`` = ``SAP`` path (0 SMU side, initial; 1 AUX), ``asu_1pa_auto`` = ``SAR`` 1 pA auto ranging enabled
    (initial: disabled), ``asu_indicator`` = ``SAL`` indicator enabled (initial: enabled). ``CN`` and ``CL`` return
    the path to the SMU side (PG p505 (4-187)); ``*RST``/device clear reset all three.

    WP8.1: ``cmu`` = MFCMU channel -> ``CmuPersistent`` (phase compensation mode, correction list, standards and data;
    ``*RST`` resets only the mode), ``scuu_paths`` = MFCMU channel -> ``SSP`` path 1-4 of its SCUU (missing = both
    outputs open, the power-on and ``*RST`` state), ``scuu_indicators`` = MFCMU channel -> ``SSL`` LED on (missing =
    on, the initial setting)."""

    version: int = STATE_VERSION
    scenario: str
    saved_at: str | None = None
    auto_calibration: bool = False
    selector_mode: int = Field(default=0, ge=0, le=63)
    selector_ports: dict[int, int] = Field(default_factory=dict)
    spgu_output_active: bool = False
    cmu_corrections: dict[int, dict[int, bool]] = Field(default_factory=dict)
    cmu_phase_results: dict[int, int] = Field(default_factory=dict)
    asu_paths: dict[int, int] = Field(default_factory=dict)
    asu_1pa_auto: dict[int, bool] = Field(default_factory=dict)
    asu_indicator: dict[int, bool] = Field(default_factory=dict)
    cmu: dict[int, CmuPersistent] = Field(default_factory=dict)
    scuu_paths: dict[int, int] = Field(default_factory=dict)
    scuu_indicators: dict[int, bool] = Field(default_factory=dict)
    channels: dict[int, ChannelState] = Field(default_factory=dict)
    devices: dict[str, dict[str, float | int | bool | str]] = Field(default_factory=dict)
    measurement_count: int = 0
    next_seq: int = 0
    log_dropped: int = 0
    command_log: list[CommandRecord] = Field(default_factory=list)

    def trim_log(self) -> None:
        """Keep at most ``COMMAND_LOG_LIMIT`` records."""
        excess = len(self.command_log) - COMMAND_LOG_LIMIT
        if excess > 0:
            del self.command_log[:excess]
            self.log_dropped += excess


def sim_state_file(state_dir: Path, scenario: str) -> Path:
    """``<state_dir>/sim/<scenario>.state.json``."""
    return Path(state_dir) / "sim" / f"{scenario}.state.json"


def load_state_file(path: Path) -> SimPersistentState | None:
    """The stored state, or ``None`` when the file does not exist. Raises ``ValueError`` for a corrupt file."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        state = SimPersistentState.model_validate_json(raw)
    except ValueError as exc:
        raise ValueError(f"Corrupt simulator state file {path}: {exc}") from exc
    if state.version != STATE_VERSION:
        raise ValueError(f"Simulator state file {path} has version {state.version}, expected {STATE_VERSION}.")
    return state


def save_state_file(path: Path, state: SimPersistentState) -> None:
    """Write ``state`` atomically (temporary file + ``os.replace``): the newest ``COMMAND_LOG_LIMIT`` command
    records (older ones counted in ``log_dropped``) and the save time. ``state`` itself is not modified, so callers
    pass the live state without a deep copy, and the compact JSON uses the C encoder: a 4 h simulated run saves its
    state at checkpoints, where a deep copy plus indented JSON of thousands of records cost tens of milliseconds a
    save (WP6.5)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = state.model_dump(mode="json")
    excess = len(record["command_log"]) - COMMAND_LOG_LIMIT
    if excess > 0:
        record["command_log"] = record["command_log"][excess:]
        record["log_dropped"] = record["log_dropped"] + excess
    record["saved_at"] = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    data = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data + "\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
