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
ERR_SYNC_MODE = 224
ERR_NO_PULSE_SWEEP = 221
ERR_NO_PULSE_BIAS = 222
ERR_NO_SYNC_DATA = 225
ERR_PULSE_LINEAR = 226
ERR_NO_PULSE_SOURCE = 230
ERR_PULSE_COMPLIANCE = 231
ERR_PULSE_SETUP = 232
ERR_PULSE_TIMING = 233
ERR_PULSE_WIDTH_MAX = 238
ERR_PULSE_WIDTH_MIN = 239
ERR_NO_CV_SWEEP = 280
ERR_NO_CV_PULSE = 281
ERR_NO_CV_PULSE_SWEEP = 282
ERR_CV_PULSE_LINEAR = 283
ERR_CMU_PULSE_WIDTH = 284
ERR_NO_CF_SWEEP = 290
ERR_CMU_EXCESS_CURRENT = 320
ERR_NOT_FOR_CMU = 321
ERR_NOT_FOR_SMU = 322
ERR_SCUU_USE_SSP = 323
ERR_SSP_CHANNEL = 671
ERR_ADJ_NOT_MANUAL = 680
ERR_CORR_STANDARD = 682
ERR_CORR_AC_ZERO = 684
ERR_CORR_INCOMPLETE = 685
ERR_SPGU_MODULE = 2000
ERR_SPGU_SOURCE = 2002
ERR_SPGU_NOT_PG = 2003
ERR_SPGU_NOT_ALWG = 2004
ERR_SPGU_LOAD = 2101
ERR_SPGU_PERIOD = 2103
ERR_SPGU_COUNT = 2104
ERR_SPGU_LEVEL = 2105
ERR_SPGU_SUM = 2106
ERR_SPGU_AMPLITUDE = 2107
ERR_SPGU_TRANSITION = 2108
ERR_SPGU_LEADING = 2111
ERR_SPGU_PERIOD_FIT = 2112
ERR_SPGU_DELAY = 2113
ERR_SPGU_WIDTH = 2114
ERR_SPGU_DURATION = 2115
ERR_SPGU_SWITCH_FIT = 2121
ERR_SPGU_SWITCH_DELAY = 2122
ERR_SPGU_SWITCH_WIDTH = 2123
ERR_SPGU_ADC_FIT = 2131
ERR_SPGU_ADC_DELAY = 2132
ERR_SPGU_ADC_INTERVAL = 2133
ERR_SPGU_ADC_COUNT = 2134
ERR_ALWG_NO_SEQUENCE = 2151
ERR_ALWG_SEQUENCE_SIZE = 2152
ERR_ALWG_INDEX = 2153
ERR_ALWG_REPEAT = 2154
ERR_ALWG_NO_PATTERN = 2155
ERR_ALWG_PATTERN_SIZE = 2156
ERR_ALWG_TIME = 2157
ERR_ALWG_LEVEL = 2158
ERR_SPGU_LOW_VOLTAGE = 2204

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
    224: "Sweep and sync output modes must be the same.",
    221: "Send PWV or PWI to set pulse sweep source.",
    222: "Send PV or PI to set pulse source.",
    225: "Send WSV, WSI, or WNX to get sync sweep data.",
    226: "Set linear sweep for MM4 or MM5.",
    230: "Pulse source must be set.",
    231: "Compliance must be set correctly.",
    232: "Invalid pulse output setup",
    233: "Invalid pulse timing setup",
    238: "Too large pulse width (max. 2 s).",
    239: "Pulse width must be 0.01 ms or more.",
    227: "Sweep measurement was aborted.",
    240: "Enter QSV to set QSCV sweep source.",
    241: "QSR range value must be -9 to -14.",
    242: "QSCV measurement was aborted.",
    243: "Enter MM13 before QSZ.",
    244: "Set a longer integration time to QST.",
    245: "Specify a higher measurement range to QSR.",
    246: "QSV mode value must be 1 or 3.",
    247: "Dedicated channel must be specified by QSO.",
    270: "Search source channel must be set.",
    271: "Search monitor channel must be set.",
    273: "Search and sync output modes must be the same.",
    275: "Search target must be compliance value or less.",
    276: "Start and stop must be different.",
    277: "Step must be output resolution or more.",
    278: "Search and sync channels must be different.",
    279: "Search monitor mode must be compliance side.",
    610: "Quasi-pulse source channel must be set.",
    280: "Send WDCV to set CV sweep source.",
    281: "Send PDCV to set CV pulse source.",
    282: "Send PWDCV to set CV pulse sweep source.",
    283: "Set linear sweep for MM20.",
    284: "Improper setting of CMU frequency and pulse width.",
    290: "Send WFC to set Cf sweep source.",
    305: "Excess current in HPSMU.",
    320: "Excess current in CMU.",
    321: "This command is not available for CMU.",
    322: "This command is not available for SMU.",
    323: "Use SSP instead of CN for SCUU modules.",
    671: "SSP is not available for this channel.",
    680: "CMU correction mode must be manual.",
    682: "Invalid standard is specified as CMU correction.",
    684: "AC Voltage is 0 mV.",
    685: "CMU correction is not complete.",
    2000: "SPGU module does not exist.",
    2002: "SPGU signal source does not exist.",
    2003: "SPGU operation mode must be PG. (SIM 0).",
    2004: "SPGU operation mode must be ALWG (SIM 1).",
    2101: "Specified load impedance is out of absolute limits.",
    2103: "Specified period is out of absolute limits.",
    2104: "Specified trigger count is out of absolute limits.",
    2105: "Specified load voltage is out of range.",
    2106: "Specified load voltage of added amplitude is out of range.",
    2107: "Specified voltage is out of absolute limits (can't achieve amplitude).",
    2108: "Specified transition time is out of absolute limits.",
    2111: "Leading/0.8 must be within Width value.",
    2112: "Delay + Width + Trail/0.8 must be within Period value.",
    2113: "Specified pulse delay is out of absolute limits.",
    2114: "Specified pulse width is out of absolute limits.",
    2115: "Specified duration is out of absolute limits.",
    2121: "Delay + Width must be within Period value (ODSW Timing).",
    2122: "Specified ODSW delay timing parameter out of absolute limits.",
    2123: "Specified ODSW width timing parameter out of absolute limits.",
    2131: "Delay + Interval * N must be within Period value (ADC Timing).",
    2132: "Specified delay for DUT impedance measurement out of absolute limits.",
    2133: "Specified interval for DUT impedance measurement out of absolute limits.",
    2134: "Specified count for DUT impedance measurement out of absolute limits.",
    2151: "ALWG Sequence Data is not ready.",
    2152: "Specified ALWG Sequence Data size is out of absolute limits.",
    2153: "Specified pattern index of ALWG Sequence Data is out of absolute limits.",
    2154: "Specified repeat count of ALWG Sequence Data is out of absolute limits.",
    2155: "ALWG Pattern Data is not ready.",
    2156: "Specified ALWG Pattern Data size is out of absolute limits.",
    2157: "Specified interval time of ALWG Pattern is out of absolute limits.",
    2158: "Specified output voltage of ALWG Pattern Data is out of absolute limits.",
    2204: "Load voltage is too small for DUT impedance measurement.",
}
"""``ERRX?`` messages for the codes the simulator raises (PG PDF 575-587; 305 from the ``ERRX?`` example, PDF 432;
the MFCMU and SCUU codes 280-290, 320-323 and 671-685 from PDF 582-583 and 586-587; the SPGU operation errors
2000-2204 from PDF 590-593; the search codes 270-279 and 610 from PDF 581-582 and 584, WP7.5; the QSCV codes
240-247 from PDF 580-581, WP8.5)."""


def error_message(code: int) -> str:
    """Message text of error ``code`` (a generic text for codes the table does not list)."""
    return ERROR_MESSAGES.get(code, f"Simulated error {code}.")


INPUT_BUFFER_CHARS = 256
"""The input buffer holds 256 characters including the terminator (PDF 44); longer lines raise error 150."""

ERROR_QUEUE_SIZE = 30
"""``ERRX?`` error queue depth (PDF 432)."""

# -- The v1 subset (blueprint 3) -------------------------------------------------------------------------------------

QUERIES = frozenset({
    "*IDN?", "UNT?", "ERRX?", "*STB?", "*OPC?", "LOP?", "*TST?", "*CAL?", "NUB?", "*LRN?",
    "ERMOD?", "ERSSP?", "SPST?", "CORRST?", "ADJ?", "CORR?", "CORRSER?", "CORRL?", "DCORR?",
})  # fmt: skip
"""Commands that put a response into the query buffer."""

SAMPLING_COMMANDS = frozenset({"MCC", "ML", "MT", "MSC", "MV", "MI", "TSR"})
"""The SMU sampling setup (``MM 10``) and the timer reset (``units/sampling.py``, v2 kind ``smu_sampling``)."""

PULSED_COMMANDS = frozenset({"PT", "PV", "PI", "PWV", "PWI", "MCPT", "MCPNT", "MCPNX", "MCPWS", "MCPWNX"})
"""The SMU pulsed setup (``MM 3/4/5/27/28``, ``units/pulsed.py``, v2 kind ``smu_pulsed``, WP7.3)."""

SEARCH_COMMANDS = frozenset({
    "LSV", "LSI", "LGV", "LGI", "LSM", "LSTM", "LSSV", "LSSI", "LSVM",
    "BSV", "BSI", "BGV", "BGI", "BSM", "BST", "BSSV", "BSSI", "BSVM", "BDV", "BDT", "BDM",
})  # fmt: skip
"""The SMU search and quasi-pulsed setup (``MM 14/15/9``, ``units/search.py``, v2 kind ``smu_search``, WP7.5)."""

QSCV_COMMANDS = frozenset({"QSV", "QST", "QSM", "QSL", "QSO", "QSC", "QSR", "QSZ"})
"""The SMU quasi-static C-V setup (``MM 13``) and the offset cancel/measurement ``QSZ`` (``units/qscv.py``, v2 kind
``smu_qscv``, WP8.5)."""

CMU_COMMANDS = frozenset({
    "IMP", "FC", "ACV", "DCV", "RC", "ACT", "LMN", "WDCV", "WTDCV", "WMDCV", "WFC", "WTFC", "WMFC", "WACV", "WTACV",
    "WMACV", "PDCV", "PTDCV", "PWDCV", "MDCV", "MTDCV", "ADJ", "CORRL", "CLCORR", "DCORR", "CORRDT", "CORRST",
})  # fmt: skip
"""MFCMU setting commands (WP8.1, blueprint v2 4.1; their queries ``ADJ?``, ``CORR?``, ``CORRST?`` and, WP8.2,
``CORRL?``, ``DCORR?`` are in ``QUERIES``)."""

SUPPORTED = (QUERIES | SAMPLING_COMMANDS | PULSED_COMMANDS | SEARCH_COMMANDS | QSCV_COMMANDS | CMU_COMMANDS
             | frozenset({
    "*RST", "FMT", "BC", "TSC", "CN", "CL", "DZ", "AB", "AAD", "AIT", "AV", "RI", "RV",
    "MM", "CMM", "DV", "WV", "WT", "WM", "XE", "CM",
    "DI", "WI", "WSV", "WSI", "WNX", "WNCC",
    "FL", "SSR", "AZ", "RM",
    "SAP", "SAR", "SAL",
    "SSP", "SSL",
    "ERMOD", "ERSSP",
    "SIM", "SPM", "SPT", "SPV", "SPPER", "SPRM", "SER", "SPUPD", "SRP", "SPP", "ODSW", "STGP", "ALW", "ALS",
}))  # fmt: skip
"""Every mnemonic the simulator executes (the v1 subset plus ``CM`` and ``*LRN?`` types 0 and 31, v2 2.6, the family
state queries of the bring-up probe, v2 7.1: ``ERMOD?``, ``ERSSP?``, ``SPST?``, ``CORRST?``, ``ADJ?`` mode 0, the
sampling commands of WP7.4 and the v2 sweep sources of WP7.2: ``DI``, ``WI``, ``WSV``/``WSI``, ``WNX``/``WNCC`` with
``MM 16``), the ASU commands of WP7.1 (``SAP``, ``SAR``, ``SAL`` with ``*LRN?`` types 62 and 63), the MFCMU and
SCUU commands of WP8.1 with ``MM`` 17-26 and ``*LRN?`` types 70-73, 80, 81, 90, the HV-SPGU commands of WP9.1,
the 16440A selector settings ``ERMOD``/``ERSSP`` of WP9.2, the SMU pulsed commands of WP7.3 with ``MM`` 3, 4, 5,
27, 28, the SMU search commands of WP7.5 with ``MM`` 9, 14, 15 and the SMU quasi-static C-V commands of WP8.5 with
``MM 13`` and ``*LRN? 49``; anything else is error 100 and logged ``unsupported``."""

ALONE_ONLY = frozenset({"AB", "*RST", "FMT", "BC"})
"""Mnemonics that must be sent alone: the simulator rejects the whole line (error 103) otherwise (PDF 44, 364,
437). The real instrument executes ``AB``/``*RST`` and silently drops the rest; the simulator is stricter so a
driver bug is loud."""

SOURCE_COMMANDS = frozenset({
    "DV", "DI", "WV", "WI", "WSV", "WSI", "WNX", "MV", "MI", "PV", "PI", "PWV", "PWI", "MCPNX", "MCPWNX",
    "LSV", "LSI", "LSSV", "LSSI", "BSV", "BSI", "BSSV", "BSSI", "BDV", "QSV",
    "ACV", "DCV", "WDCV", "WACV", "PDCV", "PWDCV", "MDCV", "SSP",
})  # fmt: skip
"""Commands that set an output level or connect an output (the safety spy watches these): the SMU sources, the MFCMU
AC level and DC bias sources and the SCUU path ``SSP`` (which switches outputs on and resets SMUs)."""

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

I_CODES_ASU = {"MPSMU": range(8, 20), "HRSMU": range(8, 20)}
"""Current range codes of an SMU with an ASU: the HRSMU gains 1 pA (8), the B1511B MPSMU 1 pA, 10 pA and 100 pA
(8-10) (Tables 4-3 and 4-5 footnotes, PDF 337/340; ``SimSlot.asu`` admits only those models)."""


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

SMU_MAX_I = 0.1
"""Largest MP/HRSMU output current (Table 4-6, PDF 341)."""

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
