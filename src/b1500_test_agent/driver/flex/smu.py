"""SMU FLEX builders: measurement operation mode, A/D converter, ranging, staircase sweeps (primary ``WV``/``WI``,
synchronous ``WSV``/``WSI``, multi-channel ``WNX``) and DC force (``DV``/``DI``) (blueprint 2.5), and the SMU
conditioning settings of blueprint v2 1.2 (WP7.7): output filter ``FL``, series resistor ``SSR``, ADC zero ``AZ``,
high-speed ADC averaging ``AV``, auto-ranging operation ``RM`` and the multi-channel sweep clear ``WNCC``.

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). Source: Keysight B1500 Series
Programming Guide, Edition 15 ("PG"); chapter 4 printed page 4-N is PDF page N + 318.
"""

from __future__ import annotations

import math

from b1500_test_agent.driver.flex.core import _channel, _choice, _int, _num

# -- Parameter domains -------------------------------------------------------------------------------------------

V_RANGE_CODES = frozenset({0, 2, 5, 11, 12, 13, 14, 15, 20, 50, 200, 400, 1000, 2000, 5000, 15000, 30000})
"""SMU voltage ranging codes (Table 4-2, PDF 335; Table 4-4, PDF 339): 0 = auto, positive = limited auto; ``RV``
also accepts the negated codes (fixed range). Expander-only codes (UHVU 103) are not accepted."""

I_RANGE_CODES = frozenset({0, *range(8, 24)})
"""SMU current ranging codes (Table 4-3, PDF 337; Table 4-5, PDF 340): 0 = auto, 8 (1 pA, ASU) to 23 (40 A) =
limited auto; ``RI`` also accepts the negated codes (fixed range). Expander-only codes (UHCU 26/28) are not
accepted."""

I_OUTPUT_RANGE_CODES = frozenset({0, *range(8, 24)})
"""SMU current output ranging codes (Table 4-5, PDF 340): 0 = auto, 8 (1 pA, ASU) to 23 (40 A) = limited auto ranging
(the minimum range that covers the output, never below the given one). Output ranging has no fixed (negative) codes;
expander-only codes (UHCU 26/28) are not accepted."""

SWEEP_SOURCE_MODES: dict[str, int] = {"V": 1, "I": 2}
"""``WNX`` source type: 1 = voltage sweep source, 2 = current sweep source (PG PDF 557, printed 4-239)."""

MAX_SWEEP_STEPS = 10001
"""``WV``/``WI`` ``step`` (number of sweep steps): 1 to 10001 (PG PDF 551, 568)."""

RM_MODES = frozenset({1, 2, 3})
"""``RM`` range changing operation: 1 = initial setting, 2 = range up after a reading >= range x rate/100, 3 = also
range down at once below range x rate/1000 (PG PDF 501-502)."""

RM_RATE_LIMITS = (11, 100)
"""``RM`` rate (percent) for modes 2 and 3: 11 to 100, default 50 (PG PDF 502)."""

AV_LIMITS = ((1, 1023), (-100, -1))
"""``AV`` number: 1 to 1023 samples (auto or manual mode) or -1 to -100 power-line cycles (PG PDF 362)."""

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



def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _compliance(value: float, name: str) -> float:
    if _finite(value, name) == 0:
        raise ValueError(f"{name} must not be 0")
    return float(value)


def _steps(points: int, name: str) -> int:
    _int(points, name)
    if not 1 <= points <= MAX_SWEEP_STEPS:
        raise ValueError(f"{name} (number of points) must be 1 to {MAX_SWEEP_STEPS}, got {points}")
    return points


def _log_polarity(mode: int, start: float, stop: float) -> None:
    if mode in (2, 4) and (float(start) == 0 or float(stop) == 0 or (float(start) > 0) != (float(stop) > 0)):
        raise ValueError("a log sweep needs non-zero start and stop of the same polarity (PG PDF 551, 569)")


# -- Builders ------------------------------------------------------------------------------------------------------


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


def di(ch: int, rng: int, i: float, vcomp: float) -> str:
    """``DI chnum,irange,current,Vcomp``: force a DC current (PG PDF 391-392, printed 4-73 to 4-74).

    ``rng`` is a current output ranging code from Table 4-5 (PDF 340; 0 = auto, positive = limited auto). Current and
    voltage compliance limits per module are in Tables 4-6, 4-8 and 4-11 (PDF 341-345; ``driver/modules.py``).
    Vcomp is always sent (never the previous setting) and must not be 0 V; its polarity stays automatic (the
    current's polarity). The channel must be enabled by ``CN``; a Vcomp above the interlock-open voltage needs the
    interlock closed.
    """
    _choice(rng, I_OUTPUT_RANGE_CODES, "DI irange")
    _finite(i, "DI current")
    _compliance(vcomp, "DI Vcomp")
    return f"DI {_channel(ch)},{rng},{_num(i)},{_num(vcomp)}"


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


def wi(ch: int, mode: int, rng: int, start: float, stop: float, points: int, vcomp: float) -> str:
    """``WI chnum,mode,range,start,stop,step,Vcomp``: staircase sweep current source (PG PDF 551-552, printed 4-233
    to 4-234).

    ``mode`` 1 linear single, 2 log single, 3 linear double (start-stop-start), 4 log double; ``rng`` from Table 4-5
    (PDF 340; the log sweep changes the output range dynamically); ``points`` = the manual's ``step``, 1 to 10001;
    log sweeps need ``start`` and ``stop`` of the same polarity and non-zero. Vcomp is always sent (its polarity
    follows the output); power compliance (``Pcomp``) is not used. ``WI`` clears the ``WV``, ``WSV``, ``WSI`` and
    ``WNX`` settings.
    """
    _choice(mode, (1, 2, 3, 4), "WI mode")
    _choice(rng, I_OUTPUT_RANGE_CODES, "WI range")
    _steps(points, "WI step")
    _finite(start, "WI start")
    _finite(stop, "WI stop")
    _log_polarity(mode, start, stop)
    _compliance(vcomp, "WI Vcomp")
    return f"WI {_channel(ch)},{mode},{rng},{_num(start)},{_num(stop)},{points},{_num(vcomp)}"


def wsv(ch: int, rng: int, start: float, stop: float, icomp: float) -> str:
    """``WSV chnum,range,start,stop,Icomp``: synchronous staircase sweep voltage source of a ``WV`` primary sweep
    (PG PDF 561-563, printed 4-243 to 4-245).

    Sent after ``WV`` (which clears it; ``WI`` clears it too); the sweep mode (linear/log, single/double) and the
    number of steps are the primary's, so a log primary needs ``start``/``stop`` of one polarity (checked by the
    staircase setup, which knows the primary). ``rng`` from Table 4-4 (PDF 339). Icomp is always sent and must not
    be 0 A; ``Pcomp`` is not used. MM 2 (and MM 4/5).
    """
    _choice(rng, V_RANGE_CODES, "WSV range")
    _finite(start, "WSV start")
    _finite(stop, "WSV stop")
    _compliance(icomp, "WSV Icomp")
    return f"WSV {_channel(ch)},{rng},{_num(start)},{_num(stop)},{_num(icomp)}"


def wsi(ch: int, rng: int, start: float, stop: float, vcomp: float) -> str:
    """``WSI chnum,range,start,stop,Vcomp``: synchronous staircase sweep current source of a ``WI`` primary sweep
    (PG PDF 560-561, printed 4-242 to 4-243).

    Sent after ``WI`` (which clears it; ``WV`` clears it too); sweep mode and steps are the primary's. ``rng`` from
    Table 4-5 (PDF 340). Vcomp is always sent and must not be 0 V; ``Pcomp`` is not used. MM 2 (and MM 4/5).
    """
    _choice(rng, I_OUTPUT_RANGE_CODES, "WSI range")
    _finite(start, "WSI start")
    _finite(stop, "WSI stop")
    _compliance(vcomp, "WSI Vcomp")
    return f"WSI {_channel(ch)},{rng},{_num(start)},{_num(stop)},{_num(vcomp)}"


def wnx(n: int, ch: int, source: str, rng: int, start: float, stop: float, comp: float) -> str:
    """``WNX N,chnum,mode,range,start,stop,comp``: sweep source number ``n`` of a multi-channel sweep
    (PG PDF 556-559, printed 4-238 to 4-241; example PDF 559).

    ``source`` ``"V"`` (mode 1, ``rng`` from Table 4-4, ``comp`` = Icomp in A) or ``"I"`` (mode 2, ``rng`` from
    Table 4-5, ``comp`` = Vcomp in V); either mode may follow either primary. ``n`` is 2 to 10 for MM 16 (the primary
    is the ``WV``/``WI`` source, which must be sent first) and 1 to 10 for MM 28; sweep mode and steps are the
    primary's. ``start`` = ``stop`` makes the channel a constant source. ``comp`` is always sent and must not be 0;
    ``Pcomp`` is not used. ``WV``/``WI``/``WNCC`` clear every ``WNX`` setting; a repeated ``n`` or channel replaces
    the earlier setting.
    """
    if _int(n, "WNX N") not in range(1, 11):
        raise ValueError(f"WNX N must be 1 to 10, got {n}")
    if source not in SWEEP_SOURCE_MODES:
        raise ValueError(f"WNX source must be 'V' or 'I', got {source!r}")
    codes = V_RANGE_CODES if source == "V" else I_OUTPUT_RANGE_CODES
    _choice(rng, codes, f"WNX range ({source} source)")
    _finite(start, "WNX start")
    _finite(stop, "WNX stop")
    _compliance(comp, "WNX comp")
    return f"WNX {n},{_channel(ch)},{SWEEP_SOURCE_MODES[source]},{rng},{_num(start)},{_num(stop)},{_num(comp)}"


# -- SMU conditioning (WP7.7, blueprint v2 1.2 "ranging RM; ADC AV/AZ; FL/SSR") --------------------------------------


def _switch(on: bool, name: str) -> int:
    if not isinstance(on, bool):
        raise TypeError(f"{name} must be True or False, got {on!r}")
    return int(on)


def fl(on: bool, chs: tuple[int, ...] | list[int] = ()) -> str:
    """``FL mode[,chnum...]``: SMU output filter connected (1) or disconnected (0, initial setting) on the channels,
    all channels without any (PG PDF 436, printed 4-118). At most ten channels."""
    channels = [_channel(ch) for ch in chs]
    if len(channels) > 10:
        raise ValueError(f"FL takes at most ten channels, got {len(channels)}")
    return ",".join([f"FL {_switch(on, 'FL mode')}", *map(str, channels)])


def ssr(ch: int, on: bool) -> str:
    """``SSR chnum,mode``: the SMU series resistor (about 1 MOhm) connected (1) or disconnected (0, initial setting)
    (PG PDF 521, printed 4-203). Not for an SMU behind an ASU or in the high-voltage state; with the output switch
    closed the output forces 0 V for a moment."""
    return f"SSR {_channel(ch)},{_switch(on, 'SSR mode')}"


def az(on: bool) -> str:
    """``AZ mode``: ADC zero function of the high-resolution ADC on (1) or off (0, initial setting); off roughly
    halves the integration time (PG PDF 363, printed 4-45)."""
    return f"AZ {_switch(on, 'AZ mode')}"


def av(number: int, mode: int | None = None) -> str:
    """``AV number[,mode]``: averaging samples of the high-speed ADC, not for the high-resolution ADC or pulsed
    measurements (PG PDF 362-363, printed 4-44 to 4-45). ``number`` 1 to 1023 (``mode`` 0 auto, the default when
    omitted: number x the initial number; 1 manual: number) or -1 to -100 power-line cycles (no mode)."""
    _int(number, "AV number")
    if not any(low <= number <= high for low, high in AV_LIMITS):
        raise ValueError(f"AV number must be 1 to 1023 or -1 to -100, got {number}")
    if mode is None:
        return f"AV {number}"
    if number < 0:
        raise ValueError("AV with a negative number (power-line cycles) takes no mode")
    return f"AV {number},{_choice(mode, range(2), 'AV mode')}"


def rm(ch: int, mode: int, rate: int | None = None) -> str:
    """``RM chnum,mode[,rate]``: auto-ranging operation of an SMU current measurement (PG PDF 501-502, printed 4-183
    to 4-184). ``mode`` 1 (initial; no rate), 2 (range up after a reading >= range x rate/100) or 3 (also down at once
    below range x rate/1000); ``rate`` 11 to 100 (default 50)."""
    _choice(mode, sorted(RM_MODES), "RM mode")
    if rate is None:
        return f"RM {_channel(ch)},{mode}"
    if mode == 1:
        raise ValueError("RM mode 1 takes no rate")
    _int(rate, "RM rate")
    if not RM_RATE_LIMITS[0] <= rate <= RM_RATE_LIMITS[1]:
        raise ValueError(f"RM rate must be {RM_RATE_LIMITS[0]} to {RM_RATE_LIMITS[1]}, got {rate}")
    return f"RM {_channel(ch)},{mode},{rate}"


def wncc() -> str:
    """``WNCC``: clears the set-up of every channel defined for the multi-channel sweep (``WNX``) (PG PDF 556, printed
    4-238)."""
    return "WNCC"
