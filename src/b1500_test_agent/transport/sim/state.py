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
    """Output state of one channel. ``voltage``/``icomp`` are the programmed DC levels (V, A)."""

    output_on: bool = False
    voltage: float = 0.0
    icomp: float | None = None
    comp_polarity: int = 0
    vrange: int = 0
    irange: int = 0


class SimPersistentState(_Mutable):
    """Contents of the state file."""

    version: int = STATE_VERSION
    scenario: str
    saved_at: str | None = None
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
    """Write ``state`` atomically (temporary file + ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.trim_log()
    state.saved_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    data = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=1)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data + "\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
