"""Core FLEX builders and constants: system queries, output switches, format and measurement mode (blueprint 2.5).

``driver/flex/`` is the only package that spells FLEX mnemonics in string literals (lint test
``tests/unit/test_lint_flex_literals.py``); ``driver/flex/__init__.py`` re-exports every builder, so callers write
``flex.cn(...)``. Builders return one command string each and never combine commands (no ``;``), so ``AB`` and
``*RST`` always travel alone. They check only what the command syntax allows (parameter domains from the manual);
module capabilities, station inventory, envelopes and policy limits are checked by ``driver/modules.py``,
``driver/guard.py`` and ``rules/``. A few builders accept less than the manual allows, on purpose: ``FMT`` 1 and 5
only (the parser handles nothing else), ``MM`` only in the modes a kind implements (``MEASUREMENT_MODES``), ``CN``
with an explicit channel list only (a bare ``CN`` enables every module). The ``*RST`` constant is sent only by
``B1500Driver.reset``, which only kind ``system`` calls (lint ``tests/unit/test_lint_rst.py``).

The syntax helpers below (``_num``, ``_int``, ``_channel``, ``_channels``, ``_choice``, ``_with_channels``) are
shared with the family modules of this package (``smu.py``; later ``cmu.py``, ``spgu.py``, ``switch.py``) and are
private to it.

Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG"). PDF page numbers are physical 1-based pages of
``B1500A Programming Guide.pdf``; chapter 4 printed page 4-N is PDF page N + 318. Every builder docstring names the
PDF (and printed) pages of its command; ``scripts/build_driver_map.py`` records the same pages in
``references/driver-map/flex-driver-map.yaml`` (a test keeps both in sync).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from b1500_test_agent.models.measurement import CHANNEL_NUMBERS

# -- Constants (each one command, always sent alone) -------------------------------------------------------------

XE = "XE"
"""Trigger the measurement set up by ``MM`` (PG PDF 570-572, printed 4-252 to 4-254). Required before ``XE`` for a
staircase sweep: ``CN``, ``MM``, ``WV`` (Table 4-33, PDF 571). The data goes to the output data buffer."""

AB = "AB"
"""Abort the present operation (PG PDF 351-352, printed 4-33 to 4-34). Sent alone: inside a command string the
other commands are not executed. Does not stop a DC bias; a staircase sweep source returns to its start value."""

IDN_Q = "*IDN?"
"""Identification query (PG PDF 440, printed 4-122): ``manufacturer,model,0,revision``."""

UNT_Q = "UNT?"
"""Module inventory query (PG PDF 545, printed 4-227): ``Slot1Model,Slot1Revision;...;Slot10Model,Slot10Revision``."""

ERRX_Q = "ERRX?"
"""Error queue query, one entry per call (PG PDF 431-432, printed 4-113 to 4-114): ``code,"message"``."""

STB_Q = "*STB?"
"""Status byte query (PG PDF 523, printed 4-205); does not clear the status byte, unlike a serial poll."""

OPC_Q = "*OPC?"
"""Operation complete query (PG PDF 479-480, printed 4-161 to 4-162): answers ``1`` once all pending operations are
complete."""

LOP_Q = "LOP?"
"""Operation status of all modules (PG PDF 446-447, printed 4-128 to 4-129): ``LOP`` + ten two-digit codes, one per
slot (Table 4-26). Used to verify that all outputs are off after cleanup (ATV-1)."""

LOP_RESPONSE_PREFIX = "LOP"
"""Header of the ``LOP?`` response; the manual's example is ``LOP00,11,00,00,00,00,00,00,00,00`` (PDF 447)."""

RST = "*RST"
"""Reset to the initial settings (PG PDF 502-503, printed 4-184 to 4-185). During a sweep send ``AB`` first; never
combined with other commands."""

SER_SETTING = "SER"
"""Name of the HV-SPGU load-impedance setting (``SER chnum,loadZ``, PG PDF 507, printed 4-189) that the output level
is adjusted to; the plan summary shows an SPGU pulse's load under this name (blueprint v2 2.9). Not sent on its own."""

TST_Q = "*TST?"
"""Self-test and self-calibration of all modules and the mainframe (PG PDF 540-541, printed 4-222 to 4-223);
answers the sum of failure bits (Table 4-32), 0 = passed. Modules end in the ``CL`` state; open the terminals
first."""

CAL_Q = "*CAL?"
"""Self-calibration of all modules and the mainframe (PG PDF 376-377, printed 4-58 to 4-59); answers the sum of
failure bits, 0 = passed. Modules end in the ``CL`` state; open the terminals first."""

# -- Parameter domains -------------------------------------------------------------------------------------------

MAX_CHANNELS_CN_CL_DZ = 15
"""``CN``, ``CL`` and ``DZ`` take at most 15 channels (PDF 378, 381, 397)."""

MAX_CHANNELS_MM = 10
"""``MM`` modes 1, 2, 10 and 16 take at most ten channels (PDF 470)."""

FORMATS = frozenset({1, 5})
"""``FMT`` formats this driver sends: ASCII with header, CR/LF (1) or comma (5) terminated (Table 4-24, PDF 437)."""

MEASUREMENT_MODES = frozenset({1, 2, 10, 16, 17, 18, 19, 20, 22, 23, 26})
"""``MM`` modes this driver sends (Table 4-28, PDF 471-472): SMU 1 spot, 2 staircase sweep, 10 sampling, 16
multi-channel sweep; MFCMU 17 spot C, 18 C-V (DC bias) sweep, 19 pulsed spot C, 20 pulsed sweep C-V, 22 C-f sweep, 23
C-V (AC level) sweep, 26 C-t sampling."""

ONE_CHANNEL_MODES = frozenset({3, 4, 5, 17, 19, 20, 22, 23, 26})
"""``MM`` modes whose syntax takes exactly one channel (PDF 470); mode 18 takes the MFCMU first, then up to nine SMU
measurement channels."""

LRN_TYPES = range(111)
"""``*LRN?`` type parameter: 0 to 110 (some numbers unused; PG PDF 447, printed 4-129)."""

LRN_SETTINGS = 31
"""``*LRN? 31``: ``TM``, ``AV``, ``CM``, ``FMT`` and ``MM`` settings (PG PDF 448, printed 4-130)."""

LRN_AUTO_CALIBRATION = "CM"
"""The ``*LRN? 31`` response item that holds the auto-calibration mode (``CM 0|1``, PG PDF 448)."""


def _num(value: float) -> str:
    """Format a numeric expression: shortest round-trip decimal, upper-case exponent, no trailing ``.0``."""
    if isinstance(value, bool):
        raise TypeError(f"FLEX numeric parameters must be numbers, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"FLEX numeric parameters must be finite, got {value!r}")
    if number == 0:
        return "0"
    return repr(number).removesuffix(".0").replace("e", "E")


def _int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {value!r}")
    return value


def _channel(ch: int) -> int:
    if _int(ch, "channel") not in CHANNEL_NUMBERS:
        raise ValueError(f"channel {ch} is not a B1500 channel number (PG Table 4-1: 1-10, 101/102 ... 1001/1002)")
    return ch


def _channels(chs: Sequence[int], *, limit: int, required: bool) -> list[int]:
    channels = [_channel(ch) for ch in chs]
    if required and not channels:
        raise ValueError("at least one channel is required")
    if len(channels) > limit:
        raise ValueError(f"at most {limit} channels can be set, got {len(channels)}")
    if len({ch * 100 + 1 if ch <= 10 else ch for ch in channels}) != len(channels):  # 1 and 101 are one channel
        raise ValueError(f"a channel is listed twice: {channels}")
    return channels


def _choice(value: int, allowed: Sequence[int] | frozenset[int], name: str) -> int:
    if _int(value, name) not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}, got {value}")
    return value


def _with_channels(mnemonic: str, channels: list[int]) -> str:
    return f"{mnemonic} {','.join(str(ch) for ch in channels)}" if channels else mnemonic


# -- Builders ------------------------------------------------------------------------------------------------------


def cn(chs: Sequence[int]) -> str:
    """``CN chnum[,chnum...]``: set the output switch of the channels ON (PG PDF 380-381, printed 4-62 to 4-63).

    One to 15 channels, enabled in the given order. A bare ``CN`` (all modules) is never built.
    """
    return _with_channels("CN", _channels(chs, limit=MAX_CHANNELS_CN_CL_DZ, required=True))


def cl(chs: Sequence[int] = ()) -> str:
    """``CL [chnum[,chnum...]]``: output switch OFF, 0 V, 20 V range, 100 uA compliance (PG PDF 378, printed 4-60).

    Without channels it disables all SMU, SPGU and CMU and has no execution condition; with channels, none may be in
    the high-voltage state. At most 15 channels.
    """
    return _with_channels("CL", _channels(chs, limit=MAX_CHANNELS_CN_CL_DZ, required=False))


def dz(chs: Sequence[int] = ()) -> str:
    """``DZ [chnum[,chnum...]]``: store the settings and set the channels to 0 V (PG PDF 397, printed 4-79).

    Without channels every SMU, SPGU and CMU whose output switch is ON is set to 0 V. At most 15 channels.
    """
    return _with_channels("DZ", _channels(chs, limit=MAX_CHANNELS_CN_CL_DZ, required=False))


def cm(mode: int) -> str:
    """``CM mode``: SMU auto-calibration OFF (0, initial setting) or ON (1) (PG PDF 379, printed 4-61). With it ON
    the B1500 calibrates all modules every 30 minutes once every SMU output switch has been OFF for 30 minutes, so an
    asynchronous run turns it off for its duration and restores it afterwards (blueprint v2 2.6, R-CAL-02)."""
    return f"CM {_choice(mode, (0, 1), 'CM mode')}"


def lrn_q(kind: int) -> str:
    """``*LRN? type``: the command parameter settings of one group (PG PDF 447-453, printed 4-129 to 4-135); type 0
    = output switch states, 1-10 = source state of the module in that slot, ``LRN_SETTINGS`` (31) = ``TM``, ``AV``,
    ``CM``, ``FMT`` and ``MM`` (PDF 448). A query: it changes no setting."""
    if _int(kind, "*LRN? type") not in LRN_TYPES:
        raise ValueError(f"*LRN? type must be {LRN_TYPES.start} to {LRN_TYPES.stop - 1}, got {kind}")
    return f"*LRN? {kind}"


def fmt(fmt: int = 1, mode: int = 1) -> str:
    """``FMT format,mode``: clear the output data buffer and select the data format (PG PDF 436-438, printed 4-118 to
    4-120; Tables 4-24 and 4-25).

    ``fmt`` 1 (ASCII 12 digits with header, CR/LF) or 5 (same, comma terminated); ``mode`` 0 to 10: 0 = measurement
    data only, 1 = plus the primary sweep source output (``Source_data``, status ``W``/``E``), 2 = plus the
    synchronous sweep source (MM 2/5). The manual forbids ``FMT`` in a multi-command string.
    """
    _choice(fmt, FORMATS, "FMT format")
    _choice(mode, range(11), "FMT mode")
    return f"FMT {fmt},{mode}"


def mm(mode: int, chs: Sequence[int]) -> str:
    """``MM mode,chnum[,chnum...]``: measurement mode and measurement channels (PG PDF 470-471, printed 4-152 to
    4-153; Table 4-28).

    ``mode`` 1 (spot), 2 (staircase sweep), 10 (sampling) or 16 (multi-channel sweep: ``WV``/``WI`` primary plus
    ``WNX`` sources) with one to ten channels; with several channels they measure in the given order (MM 16:
    channels on the high-speed ADC with fixed ranging first, simultaneously, PDF 471). The MFCMU modes 17, 19, 20,
    22, 23, 26 take exactly one channel (the MFCMU); 18 the MFCMU first and up to nine SMU channels (they measure
    before it at each step; data in the given order, PDF 471). Other modes are refused until a measurement kind
    implements them; that the channels are the right module types is the caller's (and the instrument's) check.
    """
    _choice(mode, MEASUREMENT_MODES, "MM mode")
    limit = 1 if mode in ONE_CHANNEL_MODES else MAX_CHANNELS_MM
    return f"MM {mode},{','.join(str(ch) for ch in _channels(chs, limit=limit, required=True))}"



def tsc(on: bool) -> str:
    """``TSC mode``: time stamp function OFF (0, initial setting) or ON (1) (PG PDF 538-539, printed 4-220 to 4-221).

    With it ON every measurement datum is preceded by a ``Time`` element (data type ``T``): the time from the last
    timer reset (``TSR``) to the start of that measurement (PG PDF 46, printed 1-26). Not available for MM 9, 14 and
    15 (quasi-pulsed spot, linear and binary search) and the 4-byte binary formats; best resolution 100 us when the
    timer is cleared at least every 100 s in FMT 1/5 (the 12-digit field keeps six significant digits).
    """
    if not isinstance(on, bool):
        raise TypeError(f"TSC takes a bool, got {on!r}")
    return f"TSC {1 if on else 0}"


def tsr(ch: int | None = None) -> str:
    """``TSR [chnum]``: clear the timer count (Time = 0) (PG PDF 539-540, printed 4-221 to 4-222), effective for all
    measurement modes whatever the ``TSC`` setting. Without ``chnum`` immediately; with an SMU or MFCMU channel
    (1-10) once, at that channel's next source output start by ``DV``, ``DI`` or ``DCV`` (its output switch must be
    ON; ``CL`` cancels it)."""
    if ch is None:
        return "TSR"
    if _int(ch, "TSR channel") not in range(1, 11):
        raise ValueError(f"TSR takes an SMU or MFCMU channel 1-10 (PG PDF 540), got {ch}")
    return f"TSR {ch}"
