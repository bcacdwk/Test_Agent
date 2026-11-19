"""Loaders for the lab fixtures in ``tests/fixtures/lab/`` (blueprint v2 4.4, 10.2 row 6.2; guardrail 10.0.8).

Two kinds of files, both derived from the read-only lab code and data in ``../lwp/``:

- ``idvg_real.csv``: ONE 61-point Id-Vg curve of the lab's transistor, data rows unchanged, header reduced to the
  instrument model and firmware (``%`` comment lines, then ``V_G,I_D,I_G,V_D,V_S``: programmed gate voltage, measured
  drain and gate current, programmed drain and source voltage). The lab parser dropped the instrument's status codes,
  so the rows carry none (they are read as ``N``). One of the only two lwp-derived data samples the plan allows.
- ``lwp_<script>.txt``: the FLEX command sequence a lab MATLAB script sends, reconstructed by reading its code (no
  instrument data). A header of ``# key: value`` lines (``source``, ``kind: lwp_sequence``, ``configuration``, any
  number of ``note``), then one bus operation per line: the command exactly as the script writes it (``<read>`` = a
  data read without a command), two blanks, ``#``, the lwp file and line(s) that send it and an optional remark.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from b1500_test_agent.analysis.dataset import RunData
from b1500_test_agent.models.analysis import Quantity
from tests.unit.analysis_helpers import idvg_table, manifest

LAB_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "lab"
REAL_IDVG = LAB_DIR / "idvg_real.csv"
REAL_VD = 0.1
"""Drain bias of the lab curve (V; lwp ``test_IdVg.m`` line 19, column ``V_D``)."""



def lwp_dir() -> Path:
    """Where the read-only lab code lives: ``<manuals dir>/lwp/matlab_B1500`` (``B1500_MANUALS_DIR``, default the
    repository's parent, as for the WGFMU guide ``lwp/matlab_B1500/9018-01706.pdf`` in the manual catalog). Present
    on the developer Mac only; tests that read it skip elsewhere."""
    base = os.environ.get("B1500_MANUALS_DIR") or str(Path(__file__).resolve().parents[2].parent)
    return Path(base) / "lwp" / "matlab_B1500"

READ = "<read>"
_STEP = re.compile(r"^(?P<command>\S.*?)  # (?P<file>[\w./]+\.m):(?P<lines>[\d,\-]+)(?: (?P<remark>.*))?$")


def real_idvg() -> pd.DataFrame:
    """The lab curve as a table (columns ``V_G``, ``I_D``, ``I_G``, ``V_D``, ``V_S``)."""
    return pd.read_csv(REAL_IDVG, comment="%")


def real_idvg_header() -> list[str]:
    """The comment lines of ``idvg_real.csv`` without the leading ``%``."""
    return [line[1:].strip() for line in REAL_IDVG.read_text(encoding="utf-8").splitlines() if line.startswith("%")]


def real_idvg_run() -> RunData:
    """The lab curve as ``RunData`` of ``mosfet.idvg`` (``gate_V``, ``drain_I``, ``gate_I``, all status ``N``;
    resolved ``vd`` = 0.1 V) for the analysis methods."""
    table = real_idvg()
    data = idvg_table(table["V_G"].to_numpy(), table["I_D"].to_numpy(), gate_i=table["I_G"].to_numpy())
    params = {"vg_start": Quantity(value=-2.0, unit="V"), "vg_stop": Quantity(value=2.0, unit="V"),
              "vg_points": Quantity(value=len(table)), "vd": Quantity(value=REAL_VD, unit="V")}
    return RunData(manifest(params=params), data)


@dataclass(frozen=True)
class LabStep:
    """One bus operation of a lab script: ``command`` as written (or ``<read>``), the lwp ``file`` and ``lines``."""

    command: str
    file: str
    lines: str
    remark: str = ""

    @property
    def mnemonic(self) -> str:
        return self.command if self.command == READ else self.command.split(" ", 1)[0]

    @property
    def args(self) -> list[str]:
        parts = self.command.split(" ", 1)
        return parts[1].split(",") if len(parts) > 1 else []

    @property
    def is_query(self) -> bool:
        return self.mnemonic.endswith("?")

    def line_numbers(self) -> list[int]:
        """Every line number named (``92-94,100`` -> 92, 93, 94, 100)."""
        numbers: list[int] = []
        for part in self.lines.split(","):
            lo, _, hi = part.partition("-")
            numbers += list(range(int(lo), int(hi or lo) + 1))
        return numbers


@dataclass(frozen=True)
class LabSequence:
    path: Path
    source: str
    kind: str
    configuration: str
    notes: tuple[str, ...]
    steps: tuple[LabStep, ...]

    def writes(self) -> list[str]:
        """The commands that are not queries or reads, in order."""
        return [s.command for s in self.steps if not s.is_query and s.command != READ]


def load_sequence(name: str) -> LabSequence:
    """Parse ``tests/fixtures/lab/<name>.txt``; raises ``ValueError`` when it breaks the convention."""
    path = LAB_DIR / f"{name}.txt"
    header: dict[str, list[str]] = {}
    steps: list[LabStep] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith("#"):
            if steps:
                raise ValueError(f"{path.name}:{number}: header line after the first command")
            key, sep, value = line[1:].strip().partition(":")
            if not sep:
                raise ValueError(f"{path.name}:{number}: header line without 'key:'")
            header.setdefault(key.strip(), []).append(value.strip())
            continue
        match = _STEP.match(line)
        if match is None:
            raise ValueError(f"{path.name}:{number}: not '<command>  # <file>.m:<lines> [remark]': {line!r}")
        steps.append(LabStep(command=match["command"], file=match["file"], lines=match["lines"],
                             remark=(match["remark"] or "").strip()))
    for key in ("source", "kind", "configuration"):
        if len(header.get(key, [])) != 1:
            raise ValueError(f"{path.name}: header needs exactly one '{key}:' line")
    if header["kind"] != ["lwp_sequence"]:
        raise ValueError(f"{path.name}: kind must be lwp_sequence")
    if not steps:
        raise ValueError(f"{path.name}: no command lines")
    return LabSequence(path=path, source=header["source"][0], kind=header["kind"][0],
                       configuration=header["configuration"][0], notes=tuple(header.get("note", [])),
                       steps=tuple(steps))


SEQUENCES = ("lwp_test_idvg", "lwp_test_ivt_sampling", "lwp_test_spgu")


def log_decades(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``log10(|a| / |b|)`` element by element (decades between two current arrays)."""
    return np.log10(np.abs(a)) - np.log10(np.abs(b))
