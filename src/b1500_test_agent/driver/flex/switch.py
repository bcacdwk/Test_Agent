"""Switch FLEX builders and constants: the 16440A SMU/PGU selector over the digital I/O port, the atto sense and
switch unit (ASU) of an HRSMU or B1511B MPSMU and the SCUU (SMU CMU unify unit) paths (blueprint v2 2.5).

WP6.1 adds the read-only queries the bring-up probe needs (``ERMOD?``, ``ERSSP?``); WP7.1 the ASU commands (``SAP``
path, ``SAR`` 1 pA auto ranging, ``SAL`` indicator) and the two ``*LRN?`` types that read them back (62, 63); WP8.1
the SCUU path and indicator (``SSP``, ``SSL``; the manual has no ``SSP?``: ``*LRN? 81`` answers the path,
``LRN_SCUU_PATH``); WP9.2 the selector setting commands (``ERMOD``, ``ERSSP``). Builders check only the syntax domain
of the manual (including the CH 1-only PGU-open state of the 16440A, PG p154 (2-66)).

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"; physical PDF pages, chapter 4 printed 4-N =
PDF N + 318).
"""

from __future__ import annotations

from typing import Final

from b1500_test_agent.driver.flex.core import _channel, _choice, _int
from b1500_test_agent.models.routing import PGU_OPEN_PORTS, SELECTOR_PORTS, SwitchState

ERMOD_Q = "ERMOD?"
"""Control mode of the digital I/O port (PG PDF 420-421, printed 4-102 to 4-103): the sum of the enabled mode values,
0 = general purpose (initial setting), 1 = 16440A SMU/PGU selector, 2 = N1258A/N1259A, 4 = N1265A, 8 = N1266A,
16 = N1268A, 32 = N1272A. A query: it changes no setting."""

ERMOD_SELECTOR = 1
"""The ``ERMOD?`` mode value (bit) of the 16440A selector control mode; ``ERSSP`` needs it (PG PDF 433)."""

ERMOD_MAX = 63
"""Largest ``ERMOD?`` answer: every control mode of PDF 421 enabled (1 + 2 + 4 + 8 + 16 + 32)."""

ERMOD_MODES: Final = (0, 1, 2, 4, 8, 16, 32)
"""``ERMOD`` control modes (PG PDF 419, printed 4-101): 0 general purpose (initial setting), 1 16440A selector, 2
N1258A/N1259A, 4 N1265A, 8 N1266A, 16 N1268A, 32 N1272A."""

ERSSP_STATES: Final[dict[int, SwitchState]] = {0: "open", 1: "smu", 2: "pgu", 3: "pgu_open"}
"""``ERSSP``/``ERSSP?`` connection status (PG PDF 433-434, printed 4-115 to 4-116): 0 all open (initial setting),
1 SMU on, 2 PGU on, 3 PGU open (the semiconductor relay on the PGU path open)."""

ERSSP_CODES: Final[dict[SwitchState, int]] = {state: code for code, state in ERSSP_STATES.items()}
"""Selector route state -> ``ERSSP`` status code."""


def ermod(mode: int, enable: bool = True) -> str:
    """``ERMOD mode[,option]``: select a digital I/O control mode (PG PDF 419-420, printed 4-101 to 4-102); ``mode``
    one of ``ERMOD_MODES`` (``ERMOD_SELECTOR`` = 1 for the 16440A), ``enable`` True sends the manual's form
    ``ERMOD 1`` (option 1, the default, enables the mode), False adds option 0 (disables it). Several modes may be on
    at once (``ERMOD?`` answers their sum, PDF 421). A mode setting: no output change."""
    if not isinstance(enable, bool):
        raise TypeError(f"ERMOD option must be a bool, got {enable!r}")
    code = _choice(mode, ERMOD_MODES, "ERMOD mode")
    return f"ERMOD {code}" if enable else f"ERMOD {code},0"


def erssp(port: int, status: int) -> str:
    """``ERSSP port,status``: connect one 16440A selector output (PG PDF 433, printed 4-115): port 0/1 = output 1/2
    of the first selector, 2/3 = output 1/2 of the second; status 0 all open, 1 SMU on, 2 PGU on, 3 PGU open
    (``ERSSP_STATES``). PGU open exists only on CH 1 of each selector, i.e. ports 0 and 2 (PG PDF 154, printed 2-66).
    Needs the 16440A control mode (``ERMOD 1``). Connecting an input to the DUT is a route
    (``OutputGuard.check_route``)."""
    if _int(port, "ERSSP port") not in SELECTOR_PORTS:
        raise ValueError(f"ERSSP port must be 0 to 3, got {port}")
    code = _choice(status, tuple(ERSSP_STATES), "ERSSP status")
    if ERSSP_STATES[code] == "pgu_open" and port not in PGU_OPEN_PORTS:
        raise ValueError(f"ERSSP {port},{code}: PGU open exists only on CH 1 of a selector (ports 0 and 2)")
    return f"ERSSP {port},{code}"


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


# -- SCUU (SMU CMU unify unit) ----------------------------------------------------------------------------------------

SSP_PATHS: Final[dict[int, tuple[SwitchState, SwitchState]]] = {
    1: ("smu", "open"), 2: ("open", "smu"), 3: ("smu", "smu"), 4: ("cmu", "cmu"),
}  # fmt: skip
"""``SSP chnum,path`` -> what the two SCUU outputs connect to (Table 4-30, PG PDF 520; Table 1-5, PDF 37): output 1
(CMUH / Force1, the SMU in slot ``slot - 1``) and output 2 (CMUL / Force2, the SMU in slot ``slot - 2``), where
``slot`` is the MFCMU's. Power-on and ``*RST`` leave both outputs open (no ``SSP`` path does that)."""

SCUU_SMU_SLOT_OFFSETS: Final[tuple[int, int]] = (1, 2)
"""Output 1 (CMUH/Force1) is fed by the SMU in slot ``cmu_slot - 1``, output 2 (CMUL/Force2) by ``cmu_slot - 2``
(PG PDF 520-521)."""

LRN_SCUU_ITEM = "SSP"
"""The item name of the ``*LRN? 81`` answer (PG PDF 452)."""

LRN_SCUU_PATH = 81
"""``*LRN? 81``: the SCUU connection path, ``SSP chnum,mode`` (PG PDF 452, printed 4-134); the manual has no
``SSP?`` query, so this is how the path is read back."""


def _scuu_cmu(ch: int, mnemonic: str) -> int:
    """The MFCMU channel of an SCUU command: 3 to 10 or 301 to 1001 (two SMU slots below it; PG PDF 519-520)."""
    slot = _channel(ch) if ch <= 10 else _channel(ch) // 100
    if slot < 3 or (ch > 10 and ch % 100 != 1):
        raise ValueError(f"{mnemonic} chnum must be an MFCMU channel 3 to 10 or 301 to 1001, got {ch}")
    return ch


def ssp(ch: int, path: int) -> str:
    """``SSP chnum,path``: connect the SCUU outputs (PG PDF 519-521, printed 4-201 to 4-203; ``SSP_PATHS``): 1
    Force1/Sense1 to output 1, 2 Force2/Sense2 to output 2, 3 both SMUs, 4 CMUH/CMUL. Making a connection switches
    the connected unit's output ON; switching from SMU to MFCMU sets the SMU to 0 V, 100 V range, 20 mA compliance,
    series resistor off; back to SMU: 0 V, 20 V range, 100 uA compliance (ATV-27). ``chnum`` is the MFCMU channel."""
    return f"SSP {_scuu_cmu(ch, 'SSP')},{_choice(path, tuple(SSP_PATHS), 'SSP path')}"


def ssl(ch: int, on: bool) -> str:
    """``SSL chnum,mode``: SCUU connection status indicator (LED) 1 enabled (initial setting) or 0 disabled (PG
    PDF 519, printed 4-201). No output change."""
    if not isinstance(on, bool):
        raise TypeError(f"SSL mode must be a bool, got {on!r}")
    return f"SSL {_scuu_cmu(ch, 'SSL')},{1 if on else 0}"
