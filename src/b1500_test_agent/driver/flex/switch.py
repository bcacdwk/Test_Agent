"""Switch FLEX builders and constants: the 16440A SMU/PGU selector over the digital I/O port and the atto sense and
switch unit (ASU) of an HRSMU or B1511B MPSMU (blueprint v2 2.5).

WP6.1 adds the read-only queries the bring-up probe needs (``ERMOD?``, ``ERSSP?``); WP7.1 the ASU commands (``SAP``
path, ``SAR`` 1 pA auto ranging, ``SAL`` indicator) and the two ``*LRN?`` types that read them back (62, 63). The
selector setting commands (``ERMOD``, ``ERSSP``) arrive with WP9.2 and the SCUU (``SSP``, ``SSL``) with WP8.1.
Builders check only the syntax domain of the manual.

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

from typing import Final

from b1500_test_agent.driver.flex.core import _channel, _choice, _int
from b1500_test_agent.models.routing import SELECTOR_PORTS, SwitchState

ERMOD_Q = "ERMOD?"
"""Control mode of the digital I/O port (PG PDF 420-421, printed 4-102 to 4-103): the sum of the enabled mode values,
0 = general purpose (initial setting), 1 = 16440A SMU/PGU selector, 2 = N1258A/N1259A, 4 = N1265A, 8 = N1266A,
16 = N1268A, 32 = N1272A. A query: it changes no setting."""

ERMOD_SELECTOR = 1
"""The ``ERMOD?`` mode value (bit) of the 16440A selector control mode; ``ERSSP`` needs it (PG PDF 433)."""

ERMOD_MAX = 63
"""Largest ``ERMOD?`` answer: every control mode of PDF 421 enabled (1 + 2 + 4 + 8 + 16 + 32)."""

ERSSP_STATES: Final[dict[int, SwitchState]] = {0: "open", 1: "smu", 2: "pgu", 3: "pgu_open"}
"""``ERSSP``/``ERSSP?`` connection status (PG PDF 433-434, printed 4-115 to 4-116): 0 all open (initial setting),
1 SMU on, 2 PGU on, 3 PGU open (the semiconductor relay on the PGU path open)."""


def erssp_q(port: int) -> str:
    """``ERSSP? port``: the connection status of one 16440A selector output (PG PDF 434, printed 4-116); port 0/1 =
    output 1/2 of the first selector, 2/3 = output 1/2 of the second (PDF 433). Answers 0-3 (``ERSSP_STATES``).
    A query: it changes no setting. TODO(verify) at bring-up L7 (ATV-18) whether it answers before ``ERMOD 1``."""
    if _int(port, "ERSSP? port") not in SELECTOR_PORTS:
        raise ValueError(f"ERSSP? port must be 0 to 3, got {port}")
    return f"ERSSP? {port}"


# -- ASU (atto sense and switch unit) ----------------------------------------------------------------------------

ASU_PATHS: Final[dict[int, SwitchState]] = {0: "smu", 1: "cmu"}
"""``SAP`` path (PG PDF 505-506, printed 4-187 to 4-188): 0 = the ASU output is connected to the SMU (initial
setting; also after power-on and ``CL``), 1 = to the AUX input (written ``cmu`` when the AUX input carries the
MFCMU, ``models/routing.py``)."""

ASU_PATH_CODES: Final[dict[SwitchState, int]] = {state: code for code, state in ASU_PATHS.items()}
"""Route state -> ``SAP`` path code."""

SAR_ENABLE_1PA = 0
"""``SAR`` mode that enables the 1 pA range for auto ranging (PG PDF 506, printed 4-188)."""

SAR_DISABLE_1PA = 1
"""``SAR`` mode that disables the 1 pA range for auto ranging (initial setting, PG PDF 506)."""

SAP_RESPONSE = "SAP"
"""Item mnemonic of the ``*LRN? 62`` answer: ``SAP chnum,path[;SAP chnum,path]...`` (PG PDF 451, printed 4-133)."""

SAR_RESPONSE = "SAR"
"""Item mnemonic of the ``*LRN? 63`` answer: ``SAR chnum,mode[;SAR chnum,mode]...`` (PG PDF 451, printed 4-133)."""

LRN_ASU_PATH = 62
"""``*LRN? 62``: the ASU connection path of every SMU with an ASU (PG PDF 451, printed 4-133). A query."""

LRN_ASU_1PA = 63
"""``*LRN? 63``: the 1 pA auto ranging mode of every SMU with an ASU (PG PDF 451, printed 4-133). A query."""


def sap(ch: int, path: int) -> str:
    """``SAP chnum,path``: connection path of the ASU of SMU ``ch`` (PG PDF 505-506, printed 4-187 to 4-188).

    ``path`` 0 connects the ASU output to the SMU (the SMU output appears on it at 0 V; also the state after
    power-on, ``CL`` and ``CN``), 1 to the AUX input (the SMU can then not be used). Not effective while the
    high-voltage indicator is lit. Only on an SMU with an ASU; every path change is a route
    (``OutputGuard.check_route``)."""
    return f"SAP {_channel(ch)},{_choice(path, tuple(ASU_PATHS), 'SAP path')}"


def sar(ch: int, mode: int) -> str:
    """``SAR chnum,mode``: 1 pA range for the auto ranging of SMU ``ch`` with an ASU (PG PDF 506, printed 4-188):
    ``SAR_ENABLE_1PA`` (0) enables it, ``SAR_DISABLE_1PA`` (1, initial setting) disables it. Ranging only, no
    output change."""
    return f"SAR {_channel(ch)},{_choice(mode, (SAR_ENABLE_1PA, SAR_DISABLE_1PA), 'SAR mode')}"


def sal(ch: int, mode: int) -> str:
    """``SAL chnum,mode``: connection status indicator (LED) of the ASU of SMU ``ch`` (PG PDF 505, printed 4-187):
    0 disables, 1 enables it (initial setting). No output change."""
    return f"SAL {_channel(ch)},{_choice(mode, (0, 1), 'SAL mode')}"
