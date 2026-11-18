"""FLEX command-line syntax, the v1 command subset, error messages and SMU range tables of the simulator.

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"); PDF pages are physical 1-based pages of
``B1500A Programming Guide.pdf``. Command input format (separator ``;``, 256-character input buffer,
``AB``/``*RST`` never in multi-command strings): PDF 44. ``FMT`` and ``BC`` do not allow multi-command statements
(PDF 437, 364). Error messages: Chapter 5, PDF 575-580. Range codes: Tables 4-2 to 4-5 (PDF 335-340) and output
limits Table 4-7 (PDF 342), restricted to the module types the v1 simulator drives (MPSMU, HRSMU).

This module is simulator-internal; the FLEX-literal lint exempts ``transport/sim/**``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# -- Error codes and messages (PG Chapter 5) -------------------------------------------------------------------------

ERR_UNDEFINED = 100
ERR_NUMERIC_SYNTAX = 102
ERR_TERMINATOR = 103
ERR_PARAMETER = 120
ERR_CHANNEL_NUMBER = 121
ERR_CHANNEL_COUNT = 122
ERR_RANGE = 124
ERR_LOG_POLARITY = 130
ERR_BUFFER_FULL = 150
ERR_NOT_ALLOWED = 151
ERR_NO_MODULE = 153
ERR_OUTPUT_OFF = 200
ERR_INTERLOCK = 202
ERR_DV_COMPLIANCE = 212
ERR_HV_SELFTEST = 213
ERR_NO_MM = 214
ERR_NO_SWEEP = 220
ERR_SWEEP_COMPLIANCE = 223

ERROR_MESSAGES: dict[int, str] = {
    100: "Undefined GPIB command.",
    102: "Incorrect numeric data syntax.",
    103: "Incorrect terminator position.",
    120: "Incorrect parameter value.",
    121: "Channel number must be 1 to 10.",
    122: "Number of channels must be corrected.",
    123: "Force and compliance must be set correctly.",
    124: "Incorrect range value for this channel.",
    130: "Start and stop must be same polarity.",
    150: "Command input buffer is full.",
    151: "This command is not allowed to this channel.",
    153: "No module for the specified channel.",
    200: "Channel output switch must be ON.",
    202: "Interlock circuit must be closed.",
    203: "Cannot enable channel.",
    212: "Compliance must be set correctly.",
    213: "Cannot perform self-test or calibration.",
    214: "Send MM before measurement trigger.",
    220: "Send WV or WI to set primary sweep source.",
    223: "Compliance must be set correctly.",
    227: "Sweep measurement was aborted.",
    305: "Excess current in HPSMU.",
}
"""``ERRX?`` messages for the codes the simulator raises (PG PDF 575-580; 305 from the ``ERRX?`` example, PDF 432)."""


def error_message(code: int) -> str:
    """Message text of error ``code`` (a generic text for codes the table does not list)."""
    return ERROR_MESSAGES.get(code, f"Simulated error {code}.")


INPUT_BUFFER_CHARS = 256
"""The input buffer holds 256 characters including the terminator (PDF 44); longer lines raise error 150."""

ERROR_QUEUE_SIZE = 30
"""``ERRX?`` error queue depth (PDF 432)."""

# -- The v1 subset (blueprint 3) -------------------------------------------------------------------------------------

QUERIES = frozenset({"*IDN?", "UNT?", "ERRX?", "*STB?", "*OPC?", "LOP?", "*TST?", "*CAL?", "NUB?", "*LRN?"})
"""Commands that put a response into the query buffer."""

SUPPORTED = QUERIES | frozenset({
    "*RST", "FMT", "BC", "TSC", "CN", "CL", "DZ", "AB", "AAD", "AIT", "AV", "RI", "RV",
    "MM", "CMM", "DV", "WV", "WT", "WM", "XE", "CM",
})  # fmt: skip
"""Every mnemonic the simulator executes (the v1 subset plus ``CM`` and ``*LRN?`` types 0 and 31, v2 2.6); anything
else is error 100 and logged ``unsupported``."""

ALONE_ONLY = frozenset({"AB", "*RST", "FMT", "BC"})
"""Mnemonics that must be sent alone: the simulator rejects the whole line (error 103) otherwise (PDF 44, 364,
437). The real instrument executes ``AB``/``*RST`` and silently drops the rest; the simulator is stricter so a
driver bug is loud."""

SOURCE_COMMANDS = frozenset({"DV", "WV"})
"""Commands that set an output level (the safety spy watches these)."""

ZEROING_COMMANDS = frozenset({"DZ", "CL"})
"""Commands the ``cleanup_failure`` fault makes time out."""

# -- Syntax ----------------------------------------------------------------------------------------------------------

_MNEMONIC = re.compile(r"^\s*(\*?[A-Za-z]+\??)\s*(.*?)\s*$", re.DOTALL)
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([Ee][+-]?\d+)?$")


class FlexError(Exception):
    """A command failed with instrument error ``code`` (queued for ``ERRX?``)."""

    def __init__(self, code: int, detail: str = "") -> None:
        super().__init__(f"{code}: {error_message(code)}{' ' + detail if detail else ''}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Command:
    """One command of a line: original text, upper-case mnemonic and raw argument strings."""

    text: str
    mnemonic: str
    args: tuple[str, ...]


def split_line(line: str) -> list[str]:
    """Commands of one input line (separator ``;``, blanks around it allowed; empty parts dropped)."""
    return [part.strip() for part in line.split(";") if part.strip()]


def parse_command(text: str) -> Command:
    """Split ``text`` into mnemonic and arguments; raises ``FlexError(100)`` when there is no mnemonic."""
    match = _MNEMONIC.match(text)
    if match is None:
        raise FlexError(ERR_UNDEFINED, repr(text))
    mnemonic = match.group(1).upper()
    rest = match.group(2)
    args = tuple(a.strip() for a in rest.split(",")) if rest else ()
    return Command(text=text.strip(), mnemonic=mnemonic, args=args)


def number(arg: str) -> float:
    """A numeric expression; raises ``FlexError(102)``."""
    if not _NUMBER.match(arg):
        raise FlexError(ERR_NUMERIC_SYNTAX, repr(arg))
    return float(arg)


def integer(arg: str) -> int:
    """An integer expression (an integral numeric value); raises ``FlexError(102/120)``."""
    value = number(arg)
    if value != int(value):
        raise FlexError(ERR_PARAMETER, f"{arg!r} is not an integer")
    return int(value)


def arity(cmd: Command, low: int, high: int) -> None:
    """Raise ``FlexError(103)`` unless ``low <= len(args) <= high`` (the wrong number of parameters)."""
    if not low <= len(cmd.args) <= high:
        raise FlexError(ERR_TERMINATOR, f"{cmd.mnemonic} takes {low} to {high} parameters, got {len(cmd.args)}")


# -- SMU ranges (MPSMU and HRSMU; PG Tables 4-2 to 4-7) ---------------------------------------------------------------

V_RANGE_MAX = {0: 100.0, 5: 0.5, 11: 2.0, 20: 2.0, 50: 5.0, 12: 20.0, 200: 20.0, 13: 40.0, 400: 40.0,
               14: 100.0, 1000: 100.0}
"""Voltage output range code → range (V) for MP/HRSMU (Table 4-4, PDF 339); 0 = auto (module maximum)."""

V_MEAS_CODES = frozenset({0} | {c for code in (5, 11, 20, 50, 12, 200, 13, 400, 14, 1000) for c in (code, -code)})
"""Voltage measurement ranging codes for MP/HRSMU (Table 4-2, PDF 335)."""

I_CODES = {"MPSMU": range(11, 20), "HRSMU": range(9, 20)}
"""Current range codes without the ASU: 1 nA (11) or 10 pA (9) to 100 mA (19) (Tables 4-3 and 4-5, PDF 337/340)."""


def current_range(code: int) -> float:
    """Full scale (A) of current range code ``|code|`` 8..23: 10**(code-20) (1 pA ... 1 A; Table 4-3, PDF 337)."""
    return 10.0 ** (abs(code) - 20)


def max_icomp(voltage: float) -> float:
    """Maximum |Icomp| (A) of MP/HRSMU for a voltage source at ``voltage`` (Table 4-7, PDF 342)."""
    magnitude = abs(voltage)
    if magnitude <= 20.0:
        return 0.1
    if magnitude <= 40.0:
        return 0.05
    return 0.02


SMU_MAX_V = 100.0
"""Largest MP/HRSMU output voltage (Table 4-7, PDF 342)."""

INTERLOCK_OPEN_MAX_V = 42.0
"""Allowable voltage for the interlock open condition (``INTLKVTH`` factory setting 42 V, PDF 442)."""

LINE_FREQUENCY_HZ = 50.0
"""Power-line frequency used for PLC integration times (simulator assumption)."""

SAMPLES_PER_PLC = 128
"""The high-speed ADC takes 128 samples per power-line cycle (Table 4-21, PDF 358)."""

HR_MANUAL_UNIT_S = 80e-6
"""High-resolution ADC manual-mode unit: integration time = N x 80 us (Table 4-21, PDF 359)."""

HR_AUTO_UNIT_S = 2.5e-3
"""Initial integration time of the high-resolution ADC in auto mode (not given in the PG; simulator assumption)."""
