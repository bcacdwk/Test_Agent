"""Pure FLEX command builders and command constants (blueprint 2.3).

This is the only module of the package that spells FLEX mnemonics in string literals (lint test
``tests/unit/test_lint_flex_literals.py``). Builders return one command string each and never combine commands
(no ``;``), so ``AB`` and ``*RST`` always travel alone. They check only what the command syntax allows (parameter
domains from the manual); module capabilities, station inventory, envelopes and policy limits are checked by
``driver/modules.py``, ``driver/guard.py`` and ``rules/``. A few builders accept less than the manual allows, on
purpose: ``FMT`` 1 and 5 only (the parser handles nothing else), ``MM`` 1 and 2 only (spot and staircase sweep, the
v1 kinds), ``CN`` with an explicit channel list only (a bare ``CN`` enables every module).

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
"""``MM`` modes 1 and 2 take at most ten channels (PDF 470)."""

FORMATS = frozenset({1, 5})
"""``FMT`` formats this driver sends: ASCII with header, CR/LF (1) or comma (5) terminated (Table 4-24, PDF 437)."""

MEASUREMENT_MODES = frozenset({1, 2})
"""``MM`` modes this driver sends: 1 spot, 2 staircase sweep (Table 4-28, PDF 471)."""

V_RANGE_CODES = frozenset({0, 2, 5, 11, 12, 13, 14, 15, 20, 50, 200, 400, 1000, 2000, 5000, 15000, 30000})
"""SMU voltage ranging codes (Table 4-2, PDF 335; Table 4-4, PDF 339): 0 = auto, positive = limited auto; ``RV``
also accepts the negated codes (fixed range). Expander-only codes (UHVU 103) are not accepted."""

I_RANGE_CODES = frozenset({0, *range(8, 24)})
"""SMU current ranging codes (Table 4-3, PDF 337; Table 4-5, PDF 340): 0 = auto, 8 (1 pA, ASU) to 23 (40 A) =
limited auto; ``RI`` also accepts the negated codes (fixed range). Expander-only codes (UHCU 26/28) are not
accepted."""

_AIT_N_LIMITS: dict[tuple[int, int], tuple[float, float]] = {
    (0, 0): (1, 1023),
    (0, 1): (1, 1023),
    (0, 2): (1, 100),
    (0, 3): (2e-6, 20e-3),
    (1, 0): (1, 127),
    (1, 1): (1, 127),
    (1, 2): (1, 100),
    (2, 2): (1, 100),
    (2, 3): (2e-6, 20e-3),
}
"""``AIT`` N per (ADC type, mode) from Table 4-21 (PDF 358-359): integer coefficient for modes 0-2, measurement time in
seconds (2 us to 20 ms) for mode 3. Pairs missing here are "not applicable"."""


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

    ``mode`` 1 (spot) or 2 (staircase sweep) with one to ten channels; with several channels they measure in the
    given order. Other modes are refused until a measurement kind implements them.
    """
    _choice(mode, MEASUREMENT_MODES, "MM mode")
    return f"MM {mode},{','.join(str(ch) for ch in _channels(chs, limit=MAX_CHANNELS_MM, required=True))}"


def cmm(ch: int, op: int) -> str:
    """``CMM chnum,mode``: SMU measurement operation mode (PG PDF 380, printed 4-62).

    ``op`` 0 = compliance side (initial setting), 1 = current, 2 = voltage, 3 = force side, 4 = current and voltage
    synchronous (not available for HPSMU, MPSMU and HRSMU; checked by ``driver/modules.py``).
    """
    return f"CMM {_channel(ch)},{_choice(op, range(5), 'CMM mode')}"


def aad(ch: int, adc: int) -> str:
    """``AAD chnum,type``: A/D converter of a measurement channel (PG PDF 351, printed 4-33).

    ``adc`` 0 = high-speed ADC (initial), 1 = high-resolution ADC (not for HCSMU, HVSMU, MCSMU), 2 = high-speed ADC
    for pulsed measurement.
    """
    return f"AAD {_channel(ch)},{_choice(adc, range(3), 'AAD type')}"


def ait(adc: int, mode: int, n: float) -> str:
    """``AIT type,mode,N``: operation mode and coefficient of one ADC type (PG PDF 356-359, printed 4-38 to 4-41).

    ``adc`` 0 high-speed, 1 high-resolution, 2 pulsed-measurement; ``mode`` 0 auto, 1 manual, 2 power-line cycles,
    3 measurement time. ``n`` follows Table 4-21 (PDF 358-359): integer 1-1023 (type 0, modes 0/1), 1-127 (type 1,
    modes 0/1), 1-100 (mode 2); for mode 3 a time in seconds from 2E-6 to 20E-3 (types 0 and 2). Type 1 mode 3 and
    type 2 modes 0/1 are not applicable.
    """
    _choice(adc, range(3), "AIT type")
    _choice(mode, range(4), "AIT mode")
    limits = _AIT_N_LIMITS.get((adc, mode))
    if limits is None:
        raise ValueError(f"AIT type {adc} does not support mode {mode} (PG Table 4-21)")
    low, high = limits
    if mode == 3:
        if isinstance(n, bool) or not low <= float(n) <= high:
            raise ValueError(f"AIT measurement time must be {low} to {high} s, got {n!r}")
        return f"AIT {adc},{mode},{_num(n)}"
    if isinstance(n, bool) or float(n) != int(n) or not low <= int(n) <= high:
        raise ValueError(f"AIT N for type {adc} mode {mode} must be an integer {int(low)} to {int(high)}, got {n!r}")
    return f"AIT {adc},{mode},{int(n)}"


def ri(ch: int, code: int) -> str:
    """``RI chnum,range``: current measurement range or ranging type (PG PDF 501, printed 4-183).

    ``code`` from Table 4-3 (PDF 337): 0 = auto, ``+c`` = limited auto down to range ``c``, ``-c`` = fixed range
    ``c``. Cleared by ``CL``, ``CA``, ``IN``, ``*TST?``, ``*RST`` or a device clear.
    """
    _int(code, "RI range")
    if abs(code) not in I_RANGE_CODES:
        raise ValueError(f"RI range must be 0 or +/-8 to +/-23 (PG Table 4-3), got {code}")
    return f"RI {_channel(ch)},{code}"


def rv(ch: int, code: int) -> str:
    """``RV chnum,range``: voltage measurement range or ranging type (PG PDF 503-504, printed 4-185 to 4-186).

    ``code`` from Table 4-2 (PDF 335): 0 = auto, ``+c`` = limited auto, ``-c`` = fixed. A voltage output channel
    measures with its output range regardless of this setting.
    """
    _int(code, "RV range")
    if abs(code) not in V_RANGE_CODES:
        raise ValueError(f"RV range must be 0 or +/- a PG Table 4-2 code, got {code}")
    return f"RV {_channel(ch)},{code}"


def wt(
    hold_s: float,
    delay_s: float,
    step_delay_s: float = 0.0,
    trigger_delay_s: float = 0.0,
    measure_delay_s: float = 0.0,
) -> str:
    """``WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]``: staircase sweep timing in seconds (PG PDF 564-565, printed 4-246
    to 4-247).

    ``hold`` 0-655.35 (10 ms resolution), ``delay`` 0-65.535, ``Sdelay`` 0-1.0, ``Tdelay`` 0 to ``delay``,
    ``Mdelay`` 0-65.535 (0.1 ms resolution). Unset parameters are 0 on the instrument, so optional parameters are
    sent only up to the last non-zero one. Not effective for pulsed measurements.
    """
    values = [hold_s, delay_s, step_delay_s, trigger_delay_s, measure_delay_s]
    names = ["hold", "delay", "Sdelay", "Tdelay", "Mdelay"]
    highs = [655.35, 65.535, 1.0, float(delay_s), 65.535]
    for name, value, high in zip(names, values, highs, strict=True):
        if isinstance(value, bool) or not math.isfinite(float(value)) or not 0 <= float(value) <= high:
            raise ValueError(f"WT {name} must be 0 to {high} s, got {value!r}")
    last = max(i for i, value in enumerate(values) if i < 2 or float(value) != 0)
    return "WT " + ",".join(_num(value) for value in values[: last + 1])


def wm(abort: int, post: int) -> str:
    """``WM abort,post``: automatic sweep abort and post-sweep output (PG PDF 552-553, printed 4-234 to 4-235).

    ``abort`` 1 = disabled (initial), 2 = enabled (stop on compliance, ADC overflow or oscillation; the remaining data
    are ``199.999E+99``); ``post`` 1 = start value (initial), 2 = stop value after a normal end. After an automatic
    abort the sweep sources return to the start value.
    """
    return f"WM {_choice(abort, (1, 2), 'WM abort')},{_choice(post, (1, 2), 'WM post')}"


def dv(ch: int, rng: int, v: float, icomp: float) -> str:
    """``DV chnum,vrange,voltage,Icomp``: force a DC voltage (PG PDF 396, printed 4-78).

    ``rng`` is a voltage output ranging code from Table 4-4 (PDF 339; 0 = auto, positive = limited auto). Voltage and
    compliance limits per module are in Tables 4-7, 4-9, 4-12 and 4-15 (PDF 342-346; ``driver/modules.py``). Icomp
    is always sent (0 A is not allowed); compliance polarity stays automatic. The channel must be enabled by ``CN``.
    """
    _choice(rng, V_RANGE_CODES, "DV vrange")
    if float(icomp) == 0:
        raise ValueError("DV Icomp must not be 0 A (PG PDF 396)")
    return f"DV {_channel(ch)},{rng},{_num(v)},{_num(icomp)}"


def wv(ch: int, mode: int, rng: int, start: float, stop: float, points: int, icomp: float) -> str:
    """``WV chnum,mode,range,start,stop,step,Icomp``: staircase sweep voltage source (PG PDF 568-569, printed 4-250
    to 4-251; example PDF 570).

    ``mode`` 1 linear single, 2 log single, 3 linear double (start-stop-start), 4 log double; ``rng`` from Table 4-4
    (PDF 339); ``points`` = the manual's ``step`` (number of steps), 1 to 10001; log sweeps need ``start`` and
    ``stop`` of the same polarity and non-zero. Icomp is always sent (its polarity follows the output); power
    compliance (``Pcomp``) is not used in v1. The setting is cleared by ``WI``.
    """
    _choice(mode, (1, 2, 3, 4), "WV mode")
    _choice(rng, V_RANGE_CODES, "WV range")
    _int(points, "WV step")
    if not 1 <= points <= 10001:
        raise ValueError(f"WV step (number of points) must be 1 to 10001, got {points}")
    if mode in (2, 4) and (float(start) == 0 or float(stop) == 0 or (float(start) > 0) != (float(stop) > 0)):
        raise ValueError("a log sweep needs non-zero start and stop of the same polarity (PG PDF 569)")
    if float(icomp) == 0:
        raise ValueError("WV Icomp must not be 0 A")
    return f"WV {_channel(ch)},{mode},{rng},{_num(start)},{_num(stop)},{points},{_num(icomp)}"
