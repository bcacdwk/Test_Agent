"""``WgfmuApi``: the Pythonic protocol of the Keysight B1530A WGFMU instrument library (blueprint v2 2.4, decision 6).

The library (``wgfmu.dll``) is the second instrument link next to FLEX: the waveform generator/fast measurement unit is
programmed only through it (WG p43 (3-3) "Programming Overview"). ``WgfmuApi`` is a 1:1 subset of its C functions
with Python types: string literals instead of the ``wgfmu.h`` constants, sequences and numpy arrays instead of
pointers, ``None``/values instead of output parameters, and an exception instead of a negative return code. Two
implementations: ``transport.sim.wgfmu.SimWgfmu`` (simulator, WP10.1) and ``transport.wgfmu.dll.WgfmuDll`` (ctypes,
WP10.2); ``transport.wgfmu.audit.AuditingWgfmu`` wraps either and audits every call (``ev: wgfmu_call``).

Error model (WG p148 (4-78) "Return Codes"): every C function returns ``WGFMU_NO_ERROR`` (0) or a negative library
error code (``LIBRARY_ERRORS``, WG p150-151 (4-80, 4-81)); errors the firmware reports (``OPERATION_ERRORS``, WG
p152-155 (4-82 to 4-85): 3000 module missing, 3001 RSU, 3050 memory overflow, 3301-3327 setup limits ...) reach the
caller as ``WGFMU_FW_ERROR``. A failing call raises ``WgfmuError``: ``wgfmu_code`` is the most specific code (the
firmware code for firmware errors, else the library code), ``rc`` the library return code, ``text`` the library's
error string (``WGFMU_getError``). Parameters are checked twice (WG p147 (4-77) "WGFMU Setup Functions"): against
their lowest limits when a setup function is called (out of range: ``-1``, nothing is added) and against their
highest limits by ``update``, ``execute`` (and ``exportAscii``), which then fail with the firmware code.

Constants: ``LIBRARY_CONSTANTS`` holds the ``wgfmu.h`` names and values of WG Tables 4-4 to 4-18 (p138-151); the
Pythonic maps (``OPERATION_MODES`` ...) derive from it, and ``tests/unit/test_wgfmu_api.py`` checks both against the
manual extract ``references/manuals/structured/b1530a-wgfmu-api-reference.yaml`` and the error-code extract.
``C_FUNCTIONS`` names the C functions behind every protocol method (the DLL binding binds exactly these; its
prototypes are generated from the API extract, ``scripts/gen_wgfmu_signatures.py``). ``LIMITS`` are the ALWG and
measurement limits the simulator enforces (WG p16 (1-4), p79-89 (4-9 to 4-19), p125-129 (4-55 to 4-59); WG5 p24
(1-14) Table 1-6: 2,048 vectors per pattern, 512 sequences per channel).

Channel ids: ``slot * 100 + channel`` (WG p137 (4-67) Table 4-3: ``101`` = slot 1 Ch 1 ... ``1002``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, Protocol, runtime_checkable

import numpy as np

from b1500_test_agent.models.common import ErrorCode
from b1500_test_agent.models.sources import (
    WGFMU_EVENT_TAIL_S,
    WGFMU_GRID_S,
    WGFMU_RAW_SAMPLE_S,
    WgfmuCurrentRange,
    WgfmuForceRange,
    WgfmuMode,
    WgfmuVoltageRange,
)
from b1500_test_agent.transport.base import TransportError

WgfmuMeasureMode = Literal["voltage", "current"]
"""Measurement mode of a channel (``WGFMU_setMeasureMode``)."""

# -- wgfmu.h constants (WG Tables 4-4 to 4-18) -----------------------------------------------------------------------

LIBRARY_CONSTANTS: Final[dict[str, int]] = {
    # Table 4-4 warning levels (WG p138 (4-68))
    "WGFMU_WARNING_LEVEL_OFF": 1000,
    "WGFMU_WARNING_LEVEL_SEVERE": 1001,
    "WGFMU_WARNING_LEVEL_NORMAL": 1002,
    "WGFMU_WARNING_LEVEL_INFORMATION": 1003,
    # Table 4-5 operation modes (WG p139 (4-69))
    "WGFMU_OPERATION_MODE_DC": 2000,
    "WGFMU_OPERATION_MODE_FASTIV": 2001,
    "WGFMU_OPERATION_MODE_PG": 2002,
    "WGFMU_OPERATION_MODE_SMU": 2003,
    # Table 4-6 force voltage ranges (WG p140 (4-70))
    "WGFMU_FORCE_VOLTAGE_RANGE_AUTO": 3000,
    "WGFMU_FORCE_VOLTAGE_RANGE_3V": 3001,
    "WGFMU_FORCE_VOLTAGE_RANGE_5V": 3002,
    "WGFMU_FORCE_VOLTAGE_RANGE_10V_NEGATIVE": 3003,
    "WGFMU_FORCE_VOLTAGE_RANGE_10V_POSITIVE": 3004,
    # Tables 4-7, 4-8 measurement mode and voltage measurement range (WG p141 (4-71))
    "WGFMU_MEASURE_MODE_VOLTAGE": 4000,
    "WGFMU_MEASURE_MODE_CURRENT": 4001,
    "WGFMU_MEASURE_VOLTAGE_RANGE_5V": 5001,
    "WGFMU_MEASURE_VOLTAGE_RANGE_10V": 5002,
    # Table 4-9 current measurement ranges (WG p142 (4-72))
    "WGFMU_MEASURE_CURRENT_RANGE_1UA": 6001,
    "WGFMU_MEASURE_CURRENT_RANGE_10UA": 6002,
    "WGFMU_MEASURE_CURRENT_RANGE_100UA": 6003,
    "WGFMU_MEASURE_CURRENT_RANGE_1MA": 6004,
    "WGFMU_MEASURE_CURRENT_RANGE_10MA": 6005,
    # Tables 4-10, 4-11 measurement enable, trigger output (WG p143-144 (4-73, 4-74))
    "WGFMU_MEASURE_ENABLED_DISABLE": 7000,
    "WGFMU_MEASURE_ENABLED_ENABLE": 7001,
    "WGFMU_TRIGGER_OUT_MODE_DISABLE": 8000,
    "WGFMU_TRIGGER_OUT_MODE_START_EXECUTION": 8001,
    "WGFMU_TRIGGER_OUT_MODE_START_SEQUENCE": 8002,
    "WGFMU_TRIGGER_OUT_MODE_START_PATTERN": 8003,
    "WGFMU_TRIGGER_OUT_MODE_EVENT": 8004,
    "WGFMU_TRIGGER_OUT_POLARITY_POSITIVE": 8100,
    "WGFMU_TRIGGER_OUT_POLARITY_NEGATIVE": 8101,
    # Table 4-12 merge direction (WG p144 (4-74))
    "WGFMU_AXIS_TIME": 9000,
    "WGFMU_AXIS_VOLTAGE": 9001,
    # Tables 4-13, 4-14 event completion and data output mode (WG p145 (4-75))
    "WGFMU_MEASURE_EVENT_NOT_COMPLETED": 11000,
    "WGFMU_MEASURE_EVENT_COMPLETED": 11001,
    "WGFMU_MEASURE_EVENT_DATA_AVERAGED": 12000,
    "WGFMU_MEASURE_EVENT_DATA_RAW": 12001,
    # Table 4-16 self-test/calibration results (WG p148 (4-78))
    "WGFMU_PASS": 0,
    "WGFMU_FAIL": 1,
    # Table 4-17 status codes (WG p149 (4-79))
    "WGFMU_STATUS_COMPLETED": 10000,
    "WGFMU_STATUS_DONE": 10001,
    "WGFMU_STATUS_RUNNING": 10002,
    "WGFMU_STATUS_ABORT_COMPLETED": 10003,
    "WGFMU_STATUS_ABORTED": 10004,
    "WGFMU_STATUS_RUNNING_ILLEGAL": 10005,
    "WGFMU_STATUS_IDLE": 10006,
    # Table 4-18 error codes (WG p150-151 (4-80, 4-81)); the library reserves 0 to -9999 (WG p49 (3-9))
    "WGFMU_NO_ERROR": 0,
    "WGFMU_PARAMETER_OUT_OF_RANGE_ERROR": -1,
    "WGFMU_ILLEGAL_STRING_ERROR": -2,
    "WGFMU_CONTEXT_ERROR": -3,
    "WGFMU_FUNCTION_NOT_SUPPORTED_ERROR": -4,
    "WGFMU_COMMUNICATION_ERROR": -5,
    "WGFMU_FW_ERROR": -6,
    "WGFMU_LIBRARY_ERROR": -7,
    "WGFMU_ERROR": -8,
    "WGFMU_CHANNEL_NOT_FOUND_ERROR": -9,
    "WGFMU_PATTERN_NOT_FOUND_ERROR": -10,
    "WGFMU_EVENT_NOT_FOUND_ERROR": -11,
    "WGFMU_PATTERN_ALREADY_EXISTS_ERROR": -12,
    "WGFMU_SEQUENCER_NOT_RUNNING_ERROR": -13,
    "WGFMU_RESULT_NOT_READY_ERROR": -14,
    "WGFMU_RESULT_OUT_OF_DATE_ERROR": -15,
    "WGFMU_ERROR_CODE_MIN": -9999,
}
"""``wgfmu.h`` constant name -> value (WG Tables 4-4 to 4-18)."""

_C = LIBRARY_CONSTANTS

NO_ERROR: Final = _C["WGFMU_NO_ERROR"]
PARAMETER_OUT_OF_RANGE: Final = _C["WGFMU_PARAMETER_OUT_OF_RANGE_ERROR"]
ILLEGAL_STRING: Final = _C["WGFMU_ILLEGAL_STRING_ERROR"]
CONTEXT_ERROR: Final = _C["WGFMU_CONTEXT_ERROR"]
FUNCTION_NOT_SUPPORTED: Final = _C["WGFMU_FUNCTION_NOT_SUPPORTED_ERROR"]
COMMUNICATION_ERROR: Final = _C["WGFMU_COMMUNICATION_ERROR"]
FW_ERROR: Final = _C["WGFMU_FW_ERROR"]
LIBRARY_ERROR: Final = _C["WGFMU_LIBRARY_ERROR"]
UNIDENTIFIED_ERROR: Final = _C["WGFMU_ERROR"]
CHANNEL_NOT_FOUND: Final = _C["WGFMU_CHANNEL_NOT_FOUND_ERROR"]
PATTERN_NOT_FOUND: Final = _C["WGFMU_PATTERN_NOT_FOUND_ERROR"]
EVENT_NOT_FOUND: Final = _C["WGFMU_EVENT_NOT_FOUND_ERROR"]
PATTERN_ALREADY_EXISTS: Final = _C["WGFMU_PATTERN_ALREADY_EXISTS_ERROR"]
SEQUENCER_NOT_RUNNING: Final = _C["WGFMU_SEQUENCER_NOT_RUNNING_ERROR"]
RESULT_NOT_READY: Final = _C["WGFMU_RESULT_NOT_READY_ERROR"]
RESULT_OUT_OF_DATE: Final = _C["WGFMU_RESULT_OUT_OF_DATE_ERROR"]

STATUS_COMPLETED: Final = _C["WGFMU_STATUS_COMPLETED"]
STATUS_DONE: Final = _C["WGFMU_STATUS_DONE"]
STATUS_RUNNING: Final = _C["WGFMU_STATUS_RUNNING"]
STATUS_ABORT_COMPLETED: Final = _C["WGFMU_STATUS_ABORT_COMPLETED"]
STATUS_ABORTED: Final = _C["WGFMU_STATUS_ABORTED"]
STATUS_RUNNING_ILLEGAL: Final = _C["WGFMU_STATUS_RUNNING_ILLEGAL"]
STATUS_IDLE: Final = _C["WGFMU_STATUS_IDLE"]
STATUS_NAMES: Final[dict[int, str]] = {
    STATUS_COMPLETED: "completed", STATUS_DONE: "done", STATUS_RUNNING: "running",
    STATUS_ABORT_COMPLETED: "abort_completed", STATUS_ABORTED: "aborted", STATUS_RUNNING_ILLEGAL: "running_illegal",
    STATUS_IDLE: "idle",
}  # fmt: skip
"""Status code -> short name (Table 4-17). Data cannot be read in ``running_illegal`` or ``idle``."""

WARNING_LEVELS: Final[dict[str, int]] = {
    "off": _C["WGFMU_WARNING_LEVEL_OFF"], "severe": _C["WGFMU_WARNING_LEVEL_SEVERE"],
    "normal": _C["WGFMU_WARNING_LEVEL_NORMAL"], "information": _C["WGFMU_WARNING_LEVEL_INFORMATION"],
}  # fmt: skip
"""Warning level -> code (Table 4-4); ``normal`` is the default reporting level, ``off`` the default for treating
warnings as errors."""

# -- Pythonic parameter maps -----------------------------------------------------------------------------------------

OPERATION_MODES: Final[dict[WgfmuMode, int]] = {
    "dc": _C["WGFMU_OPERATION_MODE_DC"], "fastiv": _C["WGFMU_OPERATION_MODE_FASTIV"],
    "pg": _C["WGFMU_OPERATION_MODE_PG"], "smu": _C["WGFMU_OPERATION_MODE_SMU"],
}  # fmt: skip
FORCE_VOLTAGE_RANGES: Final[dict[WgfmuForceRange, int]] = {
    "auto": _C["WGFMU_FORCE_VOLTAGE_RANGE_AUTO"], "3v": _C["WGFMU_FORCE_VOLTAGE_RANGE_3V"],
    "5v": _C["WGFMU_FORCE_VOLTAGE_RANGE_5V"], "-10v": _C["WGFMU_FORCE_VOLTAGE_RANGE_10V_NEGATIVE"],
    "10v": _C["WGFMU_FORCE_VOLTAGE_RANGE_10V_POSITIVE"],
}  # fmt: skip
MEASURE_MODES: Final[dict[WgfmuMeasureMode, int]] = {
    "voltage": _C["WGFMU_MEASURE_MODE_VOLTAGE"], "current": _C["WGFMU_MEASURE_MODE_CURRENT"],
}  # fmt: skip
MEASURE_VOLTAGE_RANGES: Final[dict[WgfmuVoltageRange, int]] = {
    "5v": _C["WGFMU_MEASURE_VOLTAGE_RANGE_5V"], "10v": _C["WGFMU_MEASURE_VOLTAGE_RANGE_10V"],
}  # fmt: skip
MEASURE_CURRENT_RANGES: Final[dict[WgfmuCurrentRange, int]] = {
    "1ua": _C["WGFMU_MEASURE_CURRENT_RANGE_1UA"], "10ua": _C["WGFMU_MEASURE_CURRENT_RANGE_10UA"],
    "100ua": _C["WGFMU_MEASURE_CURRENT_RANGE_100UA"], "1ma": _C["WGFMU_MEASURE_CURRENT_RANGE_1MA"],
    "10ma": _C["WGFMU_MEASURE_CURRENT_RANGE_10MA"],
}  # fmt: skip
MEASURE_ENABLED: Final[dict[bool, int]] = {
    False: _C["WGFMU_MEASURE_ENABLED_DISABLE"], True: _C["WGFMU_MEASURE_ENABLED_ENABLE"],
}  # fmt: skip
MEASURE_EVENT_DATA: Final[dict[bool, int]] = {
    False: _C["WGFMU_MEASURE_EVENT_DATA_AVERAGED"], True: _C["WGFMU_MEASURE_EVENT_DATA_RAW"],
}  # fmt: skip
"""``raw`` flag of ``set_measure_event`` -> ``rdata`` code (Table 4-14)."""

CURRENT_RANGE_A: Final[dict[WgfmuCurrentRange, float]] = {
    "1ua": 1e-6, "10ua": 1e-5, "100ua": 1e-4, "1ma": 1e-3, "10ma": 1e-2,
}  # fmt: skip
"""Full scale of each current measurement range (Table 4-9, controlled ranges +-full scale)."""

VOLTAGE_RANGE_V: Final[dict[WgfmuVoltageRange, float]] = {"5v": 5.0, "10v": 10.0}
"""Full scale of each voltage measurement range (Table 4-8)."""

FORCE_RANGE_BOUNDS: Final[dict[WgfmuForceRange, tuple[float, float]]] = {
    "3v": (-3.0, 3.0), "5v": (-5.0, 5.0), "-10v": (-10.0, 0.0), "10v": (0.0, 10.0),
}  # fmt: skip
"""Output bounds of each fixed force range (WG p136 (4-66) Table 4-2); ``auto`` picks the smallest that fits."""

AUTO_RANGE_ORDER: Final[tuple[WgfmuForceRange, ...]] = ("3v", "5v", "-10v", "10v")
"""Fixed force ranges in the order auto ranging tries them (smallest first; simulator convention)."""

PG_FORCE_RANGES: Final[frozenset[str]] = frozenset({"auto", "3v", "5v"})
"""Force ranges available in PG mode (Table 4-6: the 10 V ranges are not available for PG)."""

ALWG_MODES: Final[frozenset[str]] = frozenset({"fastiv", "pg"})
"""Operation modes with an arbitrary linear waveform generator (sequencer): Fast IV and PG (Table 4-4 note a)."""

CURRENT_MODES: Final[frozenset[str]] = frozenset({"fastiv", "dc"})
"""Operation modes that can measure current (Table 4-7: not PG, meaningless in SMU mode)."""

PG_OUTPUT_OHM: Final = 50.0
"""PG mode output resistance: the output voltage is divided by the internal 50 Ohm and the load (Table 4-5)."""

# -- Limits ----------------------------------------------------------------------------------------------------------

LIMITS: Final[dict[str, float]] = {
    "grid_s": WGFMU_GRID_S,                       # 10 ns resolution of vectors, event times, intervals, averages
    "vector_dt_min_s": 1e-8,                      # WGFMU_addVector dTime (WG p82 (4-12))
    "vector_dt_max_s": 10995.11627775,
    "max_abs_v": 10.0,                            # widest force range (Table 4-2)
    "max_vectors": 2048,                          # per pattern (WG5 p24 (1-14) Table 1-6)
    "max_sequences": 512,                         # per channel (WG5 p24 (1-14) Table 1-6)
    "count_min": 1.0,                             # WGFMU_addSequence count (WG p80 (4-10))
    "count_max": 1_099_511_627_776.0,
    "interval_min_s": 1e-8,                       # WGFMU_setMeasureEvent (WG p125-126 (4-55, 4-56))
    "interval_max_s": 1.34217728,
    "average_min_s": 1e-8,
    "average_max_s": 0.020971512,
    "raw_sample_s": WGFMU_RAW_SAMPLE_S,           # averaging samples every 5 ns
    "event_tail_s": WGFMU_EVENT_TAIL_S,           # event end + 10 ns when average = 0
    "memory_points": 4_000_000,                   # about 4,000,000 stored data per channel (WG p125 (4-55))
    "sequence_gap_s": 5e-8,                       # 10 ns last voltage + 40 ns next initial voltage (WG p80 (4-10))
    "sequence_gap_hold_s": 1e-8,
    "averaging_event_spacing_s": 1e-7,            # adjacent events changing averaging (WG p126 (4-56) NOTE)
    "range_event_spacing_s": 2e-6,                # three or more continuous range changes (WG p128 (4-58) NOTE)
    "timeout_default_s": 100.0,                   # WGFMU_setTimeout (WG p129 (4-59))
    "timeout_min_s": 1.0,
    "self_test_timeout_s": 600.0,
}  # fmt: skip
"""ALWG, measurement and session limits of the WGFMU and its library."""


def is_channel_id(ch: object) -> bool:
    """True for a syntactically valid WGFMU channel id (``101``, ``102`` ... ``1001``, ``1002``; Table 4-3)."""
    return isinstance(ch, int) and not isinstance(ch, bool) and 1 <= ch // 100 <= 10 and ch % 100 in (1, 2)


def channel_ids_of(wgfmu_slots: Sequence[int]) -> list[int]:
    """The channel ids of WGFMU modules in ``wgfmu_slots`` (two channels each), ascending."""
    return [slot * 100 + sub for slot in sorted(wgfmu_slots) for sub in (1, 2)]


# -- Error codes and messages ----------------------------------------------------------------------------------------

LIBRARY_ERRORS: Final[dict[int, str]] = {
    -1: "Invalid parameter value was found. It will be out of the range.",
    -2: "Invalid string value was found. It will be empty or illegal (pointer).",
    -3: "Context error was found between relative functions.",
    -4: "Specified function is not supported by this channel.",
    -5: "IO library error was found.",
    -6: "Firmware error was found.",
    -7: "WGFMU instrument library error was found.",
    -8: "Unidentified error was found.",
    -9: "Specified channel id is not available for WGFMU.",
    -10: "Unexpected pattern name was specified.",
    -11: "Unexpected event name was specified.",
    -12: "Duplicate pattern name was specified.",
    -13: "Sequencer must be run to execute the specified function.",
    -14: "Measurement is in progress. Read the result data after the measurement is completed.",
    -15: "Measurement result data was deleted by the setup change.",
}
"""Library error code -> description (WG p150-151 (4-80, 4-81) Table 4-18)."""

LIBRARY_ERROR_NAMES: Final[dict[int, str]] = {
    value: name for name, value in LIBRARY_CONSTANTS.items() if name.endswith("_ERROR") and -15 <= value <= -1
}
"""Library error code -> ``wgfmu.h`` name (``-1`` -> ``WGFMU_PARAMETER_OUT_OF_RANGE_ERROR`` ...)."""

OPERATION_ERRORS: Final[dict[int, str]] = {
    3000: "WGFMU module does not exist.",
    3001: "RSU is not connected.",
    3002: "WGFMU initialization failure.",
    3015: "Measurement data corrupted.",
    3050: "Measurement data memory overflow error.",
    3051: "Measurement data FIFO overflow error.",
    3052: "Measurement range change request error.",
    3201: "ALWG Sequence Data is not ready.",
    3202: "ALWG Waveform Data is not ready.",
    3301: "Specified output voltage is out of absolute limits.",
    3302: "Specified voltage output range is invalid.",
    3303: "Invalid measurement mode for current operation mode.",
    3304: "Specified ALWG Vector Data size is out of absolute limits.",
    3305: "Specified ALWG Sequence Data size is out of absolute limits.",
    3306: "ALWG Waveform Data is empty.",
    3307: "Specified ALWG Waveform Data size is out of absolute limits.",
    3308: "Specified waveform index of ALWG Sequence Data is out of absolute limits.",
    3309: "Specified loop number of ALWG Sequence Data is out of absolute limits.",
    3310: "Specified output voltage of ALWG Waveform Data is out of absolute limits.",
    3311: "Specified interval time of ALWG Waveform is out of absolute limits.",
    3312: "Specified ALWG measurement interval time is out of absolute limits.",
    3313: "Specified ALWG measurement instruction code is invalid.",
    3314: "Specified ALWG range change instruction code is invalid.",
    3315: "Specified ALWG measurement count is out of absolute limits.",
    3316: "Specified ALWG measurement count is greater than measurement interval.",
    3317: "Specified slot is invalid.",
    3318: "Specified module channel is invalid.",
    3319: "Output delay is out of absolute limits.",
    3320: "Measurement delay is out of absolute limits.",
    3321: "VM/IM measurement mode is invalid.",
    3322: "Voltage measurement range is invalid.",
    3323: "Current measurement range is invalid.",
    3324: "WGMA?,WGMB? command query size is out of absolute limits.",
    3325: "Specified count for spot measurement is out of absolute limits.",
    3326: "Specified interval for spot measurement is out of absolute limits.",
    3327: "Specified operation mode is invalid for spot measurement.",
}
"""Firmware operation error code -> message (WG p152-155 (4-82 to 4-85) "Operation Error", plus 3002 of the
self-test/calibration errors, which ``initialize`` can report)."""


def error_text(code: int, detail: str = "") -> str:
    """The error string for ``code`` (library or firmware), with ``detail`` (what was wrong) appended."""
    if code < 0:
        name = LIBRARY_ERROR_NAMES.get(code, "WGFMU_ERROR")
        text = f"{code} {name}: {LIBRARY_ERRORS.get(code, 'Unidentified error was found.')}"
    else:
        text = f"firmware error {code}: {OPERATION_ERRORS.get(code, 'Firmware error was found.')}"
    return f"{text} {detail}".rstrip() if detail else text


class WgfmuError(TransportError):
    """A WGFMU instrument-library call failed (``rc < 0``; blueprint v2 2.4).

    ``wgfmu_code``: the most specific code (firmware code such as 3050, else the library code such as -10);
    ``rc``: the library return code (``FW_ERROR`` for firmware errors); ``text``: the library's error string;
    ``function``: the protocol method that failed. ``code`` stays the result ``ErrorCode`` every ``B1500Error``
    carries: ``transport_error`` for communication failures (``rc`` -5, a hung call), else ``instrument_error``.
    """

    def __init__(self, code: int, text: str, *, rc: int | None = None, function: str | None = None) -> None:
        self.wgfmu_code = code
        self.text = text
        self.rc = rc if rc is not None else (code if code < 0 else FW_ERROR)
        self.function = function
        super().__init__(text if function is None or text.startswith(f"{function}:") else f"{function}: {text}")

    @property  # type: ignore[override]
    def code(self) -> ErrorCode:
        return "transport_error" if self.rc == COMMUNICATION_ERROR else "instrument_error"


# -- The protocol ----------------------------------------------------------------------------------------------------


@runtime_checkable
class WgfmuApi(Protocol):
    """Pythonic 1:1 subset of the WGFMU instrument library (blueprint v2 2.4); every method raises ``WgfmuError``
    when the library returns an error code. ``C_FUNCTIONS`` names the C functions behind each method."""

    def open_session(self, address: str) -> None:
        """Open the library's communication session with the B1500A at VISA ``address`` (WG p122 (4-52))."""
        ...

    def close_session(self) -> None:
        """Close the session (WG p84 (4-14))."""
        ...

    def initialize(self) -> None:
        """Reset every WGFMU channel: SMU mode, disconnected, 0 V; the software setup stays (WG p120 (4-50))."""
        ...

    def clear(self) -> None:
        """Clear the software setup: patterns, sequences, errors, warnings; hardware unchanged (WG p84 (4-14))."""
        ...

    def set_timeout(self, s: float) -> None:
        """Session timeout in seconds, >= 1 (default 100; WG p129 (4-59))."""
        ...

    def channel_ids(self) -> list[int]:
        """Channel ids of the installed WGFMU channels (WG p95 (4-25))."""
        ...

    def set_operation_mode(self, ch: int, mode: WgfmuMode) -> None:
        """Operation mode, applied by ``update``/``execute``/DC functions (WG p127 (4-57), Table 4-5)."""
        ...

    def set_force_voltage_range(self, ch: int, rng: WgfmuForceRange) -> None:
        """Voltage output range (WG p123 (4-53), Table 4-6)."""
        ...

    def set_measure_mode(self, ch: int, mode: WgfmuMeasureMode) -> None:
        """Voltage or current measurement; current sets the voltage measurement range to 5 V (Table 4-7)."""
        ...

    def set_measure_current_range(self, ch: int, rng: WgfmuCurrentRange) -> None:
        """Current measurement range (WG p123 (4-53), Table 4-9)."""
        ...

    def set_measure_voltage_range(self, ch: int, rng: WgfmuVoltageRange) -> None:
        """Voltage measurement range (WG p127 (4-57), Table 4-8)."""
        ...

    def set_measure_enabled(self, ch: int, on: bool) -> None:
        """Enable or disable the channel's measurement (not in DC mode; WG p124 (4-54))."""
        ...

    def create_pattern(self, name: str, v0: float) -> None:
        """Create a waveform pattern with initial voltage ``v0`` at its time origin (WG p88 (4-18))."""
        ...

    def add_vectors(self, name: str, dt: Sequence[float], v: Sequence[float]) -> None:
        """Append ``(dt, v)`` vectors (incremental times, linear ramps) to a pattern (WG p83 (4-13))."""
        ...

    def set_measure_event(self, pattern: str, event: str, t: float, points: int, interval: float, average: float,
                          raw: bool) -> None:
        """Sampling measurement while ``pattern`` is output: ``points`` every ``interval`` from ``t``, each averaged
        over ``average`` (0 = none); ``raw`` returns every 5 ns sample (WG p125-126 (4-55, 4-56))."""
        ...

    def set_range_event(self, pattern: str, event: str, t: float, rng: WgfmuCurrentRange) -> None:
        """Current-range change at ``t`` while ``pattern`` is output (Fast IV current only; WG p128 (4-58))."""
        ...

    def add_sequence(self, ch: int, pattern: str, count: float) -> None:
        """Append ``pattern`` x ``count`` to the channel's output sequence (WG p79-80 (4-9, 4-10))."""
        ...

    def update(self) -> None:
        """Apply the setup to every channel; ALWG channels output their initial voltage (WG p134 (4-64))."""
        ...

    def connect(self, ch: int) -> None:
        """Enable the channel and its RSU (WG p85 (4-15))."""
        ...

    def disconnect(self, ch: int) -> None:
        """Disable the channel and its RSU (WG p91 (4-21))."""
        ...

    def execute(self) -> None:
        """Run the sequencers of every enabled Fast IV/PG channel (WG p93 (4-23))."""
        ...

    def wait_until_completed(self) -> None:
        """Block until every connected Fast IV/PG channel is ready to read (WG p135 (4-65))."""
        ...

    def abort(self) -> None:
        """Stop every sequencer; the channels keep the voltage of that moment (WG p79 (4-9))."""
        ...

    def status(self) -> tuple[int, float, float]:
        """``(status, elapsed_s, total_s)`` over the active channels (WG p117 (4-47), Table 4-17)."""
        ...

    def channel_status(self, ch: int) -> tuple[int, float, float]:
        """``(status, elapsed_s, total_s)`` of one channel (WG p95-96 (4-25, 4-26))."""
        ...

    def measure_value_size(self, ch: int) -> tuple[int, int]:
        """``(measured, total)`` data values of the channel (WG p112 (4-42))."""
        ...

    def measure_values(self, ch: int, offset: int, size: int) -> tuple[np.ndarray, np.ndarray]:
        """``(time_s, value)`` arrays of up to ``size`` data values from index ``offset`` (WG p111 (4-41))."""
        ...

    def dc_force_voltage(self, ch: int, v: float) -> None:
        """DC output now (DC mode only; WG p89 (4-19))."""
        ...

    def dc_measure_value(self, ch: int) -> float:
        """One DC voltage or current measurement now (DC mode only; WG p90 (4-20))."""
        ...

    def self_test(self) -> int:
        """Self-test of the mainframe and modules: 0 pass, else the slot bitmask (WG p92 (4-22))."""
        ...

    def self_calibration(self) -> int:
        """Self-calibration: 0 pass, else the slot bitmask (WG p91 (4-21))."""
        ...

    def errors(self) -> list[str]:
        """Read and remove every queued error string, oldest first (WG p97 (4-27))."""
        ...


API_METHODS: Final[tuple[str, ...]] = (
    "open_session", "close_session", "initialize", "clear", "set_timeout", "channel_ids", "set_operation_mode",
    "set_force_voltage_range", "set_measure_mode", "set_measure_current_range", "set_measure_voltage_range",
    "set_measure_enabled", "create_pattern", "add_vectors", "set_measure_event", "set_range_event", "add_sequence",
    "update", "connect", "disconnect", "execute", "wait_until_completed", "abort", "status", "channel_status",
    "measure_value_size", "measure_values", "dc_force_voltage", "dc_measure_value", "self_test", "self_calibration",
    "errors",
)  # fmt: skip
"""The protocol's methods in blueprint order (test: equal to ``WgfmuApi``'s and ``models.sim.LIBRARY_FUNCTIONS``)."""

C_FUNCTIONS: Final[dict[str, tuple[str, ...]]] = {
    "open_session": ("WGFMU_openSession",),
    "close_session": ("WGFMU_closeSession",),
    "initialize": ("WGFMU_initialize",),
    "clear": ("WGFMU_clear",),
    "set_timeout": ("WGFMU_setTimeout",),
    "channel_ids": ("WGFMU_getChannelIds", "WGFMU_getChannelIdSize"),
    "set_operation_mode": ("WGFMU_setOperationMode",),
    "set_force_voltage_range": ("WGFMU_setForceVoltageRange",),
    "set_measure_mode": ("WGFMU_setMeasureMode",),
    "set_measure_current_range": ("WGFMU_setMeasureCurrentRange",),
    "set_measure_voltage_range": ("WGFMU_setMeasureVoltageRange",),
    "set_measure_enabled": ("WGFMU_setMeasureEnabled",),
    "create_pattern": ("WGFMU_createPattern",),
    "add_vectors": ("WGFMU_addVectors",),
    "set_measure_event": ("WGFMU_setMeasureEvent",),
    "set_range_event": ("WGFMU_setRangeEvent",),
    "add_sequence": ("WGFMU_addSequence",),
    "update": ("WGFMU_update",),
    "connect": ("WGFMU_connect",),
    "disconnect": ("WGFMU_disconnect",),
    "execute": ("WGFMU_execute",),
    "wait_until_completed": ("WGFMU_waitUntilCompleted",),
    "abort": ("WGFMU_abort",),
    "status": ("WGFMU_getStatus",),
    "channel_status": ("WGFMU_getChannelStatus",),
    "measure_value_size": ("WGFMU_getMeasureValueSize",),
    "measure_values": ("WGFMU_getMeasureValues",),
    "dc_force_voltage": ("WGFMU_dcforceVoltage",),
    "dc_measure_value": ("WGFMU_dcmeasureValue",),
    "self_test": ("WGFMU_doSelfTest",),
    "self_calibration": ("WGFMU_doSelfCalibration",),
    "errors": ("WGFMU_getError", "WGFMU_getErrorSize"),
}
"""Protocol method -> the C functions it calls, the audited one first (the DLL binding's ``argtypes`` table covers
exactly these; test: every name is in the API extract)."""

READBACK_CHUNK: Final = 100_000
"""Data values per ``measure_values`` call in chunked readback (the lab's practice, blueprint v2 1.1)."""
