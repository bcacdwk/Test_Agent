"""SMU sampling-measurement FLEX builders (``MM 10``): ``MCC``, ``ML``, ``MT``, ``MSC``, ``MV``, ``MI`` (blueprint v2
2.5, 2.7 kind ``smu_sampling``).

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). The sampling commands live in their
own module (not ``smu.py``) so that the SMU measurement-mode work packages touch disjoint files; ``TSC``/``TSR``
(time stamps, every mode) are in ``core.py``. Source: Keysight B1500 Series Programming Guide, Edition 15 ("PG");
chapter 4 printed page 4-N is PDF page N + 318.

Sampling operation (PG PDF 112-114, printed 2-24 to 2-26; ``MT`` PDF 475-476): on the trigger (``XE``) the ``MV``/``MI``
synchronous sources force their base value, after ``h_base`` seconds their bias value (the time origin ``t``), and
``h_bias`` seconds later the first sample is taken; then one sample per ``interval`` until ``number`` results are
held. ``time = t + h_bias + (index - 1) x interval`` for the returned sampling index. ``DV``/``DI`` sources keep their
own output throughout. ``MSC`` sets the automatic abort (compliance on any channel, oscillation, A/D overflow) and the
output after a normal end; after an automatic abort the sources force their base value and the remaining data read
``199.999E+99``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from b1500_test_agent.driver.flex.core import _channel, _channels, _choice, _int, _num, _with_channels
from b1500_test_agent.driver.flex.smu import I_RANGE_CODES, V_RANGE_CODES

# -- Parameter domains -------------------------------------------------------------------------------------------

SAMPLING_MODE = 10
"""``MM`` mode of the sampling measurement (Table 4-28, PDF 471)."""

LINEAR_SAMPLING = 1
"""``ML`` mode 1: linear sampling, the initial setting (PDF 469)."""

LOG_SAMPLING_DENSITY: dict[int, int] = {2: 10, 3: 25, 4: 50, 5: 100, 6: 250, 7: 500}
"""``ML`` modes 2-7: logarithmic sampling with that many data per decade (PDF 470)."""

LOG_SAMPLING_DECADES = 11
"""Log sampling holds at most ``1 + density x 11`` results (``MT`` number, PDF 475)."""

MT_MIN_INTERVAL_S = 0.0001
MT_MAX_INTERVAL_S = 65.535
MT_FAST_INTERVAL_S = 0.002
"""Intervals below 2 ms are linear-only, need ``interval >= 0.0001 + 0.00002 x (channels - 1)`` and allow a negative
``h_bias``; the SPGU cannot be used then (PDF 474-475)."""

MT_MAX_HOLD_S = 655.35
MT_HOLD_RESOLUTION_S = 0.01
MT_NEGATIVE_HOLD_S = (-0.09, -0.0001)
"""``h_bias`` range available only for intervals below 2 ms (0.1 ms resolution): the sampling then starts
``|h_bias|`` before the bias output (PDF 475)."""

MT_MAX_NUMBER = 100001
"""``MT`` number upper bound for one measurement channel (linear: 100001 / channels; PDF 475)."""

MAX_CHANNELS_MCC = 15
"""``MCC`` takes at most 15 channels (PDF 461)."""

SAMPLING_ABORT = {False: 1, True: 2}
"""``MSC`` abort parameter: 1 disables, 2 enables the automatic abort (PDF 473)."""

SAMPLING_POST = {"base": 1, "bias": 2}
"""``MSC`` post parameter: output after a normal end, 1 base value, 2 bias value (initial setting; PDF 473)."""


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


# -- Builders ------------------------------------------------------------------------------------------------------


def mcc(chs: Sequence[int] = ()) -> str:
    """``MCC [chnum[,chnum...]]``: clear the sampling sources set by ``MV``, ``MI`` or ``MSP`` (PG PDF 461, printed
    4-143). Without channels every sampling source is cleared; at most 15 channels."""
    return _with_channels("MCC", _channels(chs, limit=MAX_CHANNELS_MCC, required=False))


def ml(mode: int) -> str:
    """``ML mode``: sampling mode (PG PDF 469-470, printed 4-151 to 4-152): 1 linear (initial setting, also after
    ``*RST``), 2-7 logarithmic with 10, 25, 50, 100, 250 or 500 data per decade (``LOG_SAMPLING_DENSITY``). Without
    ``ML`` the last mode stays effective."""
    return f"ML {_choice(mode, (LINEAR_SAMPLING, *LOG_SAMPLING_DENSITY), 'ML mode')}"


def mt(h_bias: float, interval: float, number: int, h_base: float = 0.0) -> str:
    """``MT h_bias,interval,number,h_base``: sampling timing (PG PDF 474-476, printed 4-156 to 4-158).

    ``h_bias`` (s): bias output to the first sample, 0-655.35 in 10 ms steps; for ``interval`` < 2 ms also -0.09 to
    -0.0001 in 0.1 ms steps (sampling starts ``|h_bias|`` before the bias). ``interval`` (s): 0.0001-65.535, 1 ms
    resolution from 2 ms, 10 us below (linear sampling only; channel-count formula at ``MT_FAST_INTERVAL_S``).
    ``number``: samples, 1 to 100001 (linear: 100001 / channels; log: ``1 + density x 11``; checked by the kind).
    ``h_base`` (s): base output to bias output, 0-655.35 in 10 ms steps; always sent. Values off the resolution grid
    are refused (the instrument would round them, so the preview would not be what runs).
    """
    h_bias, interval, h_base = (_finite(v, n) for v, n in ((h_bias, "MT h_bias"), (interval, "MT interval"),
                                                             (h_base, "MT h_base")))
    if not MT_MIN_INTERVAL_S <= interval <= MT_MAX_INTERVAL_S:
        raise ValueError(f"MT interval must be {MT_MIN_INTERVAL_S} to {MT_MAX_INTERVAL_S} s, got {interval}")
    fast = interval < MT_FAST_INTERVAL_S
    if not _on_grid(interval, 0.00001 if fast else 0.001):
        raise ValueError(f"MT interval {interval} s is off its resolution ({'10 us' if fast else '1 ms'})")
    if h_bias < 0:
        low, high = MT_NEGATIVE_HOLD_S
        if not fast or not low <= h_bias <= high or not _on_grid(h_bias, 0.0001):
            raise ValueError(f"a negative MT h_bias ({h_bias} s) needs interval < 2 ms and -0.09 to -0.0001 s in "
                             "0.1 ms steps")
    elif h_bias > MT_MAX_HOLD_S or not _on_grid(h_bias, MT_HOLD_RESOLUTION_S):
        raise ValueError(f"MT h_bias must be 0 to {MT_MAX_HOLD_S} s in 10 ms steps, got {h_bias}")
    if not 0 <= h_base <= MT_MAX_HOLD_S or not _on_grid(h_base, MT_HOLD_RESOLUTION_S):
        raise ValueError(f"MT h_base must be 0 to {MT_MAX_HOLD_S} s in 10 ms steps, got {h_base}")
    if not 1 <= _int(number, "MT number") <= MT_MAX_NUMBER:
        raise ValueError(f"MT number must be 1 to {MT_MAX_NUMBER}, got {number}")
    return f"MT {_num(h_bias)},{_num(interval)},{number},{_num(h_base)}"


def msc(abort: bool, post: str | None = None) -> str:
    """``MSC abort[,post]``: automatic abort and post-measurement output of the sampling sources (PG PDF 472-473,
    printed 4-154 to 4-155).

    ``abort`` True (2) stops the measurement on compliance of a measurement or non-measurement channel, oscillation
    or A/D converter overflow; the data after the abort read ``199.999E+99`` and the sources force their base value.
    ``post`` (``base`` or ``bias``, the initial setting) is the ``MV``/``MI`` output after a normal end; omitted, the
    instrument forces the bias value. DC ``DV``/``DI`` sources keep their output either way.
    """
    if not isinstance(abort, bool):
        raise TypeError(f"MSC abort must be a bool, got {abort!r}")
    if post is None:
        return f"MSC {SAMPLING_ABORT[abort]}"
    if post not in SAMPLING_POST:
        raise ValueError(f"MSC post must be one of {sorted(SAMPLING_POST)}, got {post!r}")
    return f"MSC {SAMPLING_ABORT[abort]},{SAMPLING_POST[post]}"


def mv(ch: int, vrange: int, base: float, bias: float, icomp: float) -> str:
    """``MV chnum,vrange,base,bias,Icomp``: SMU voltage source synchronized with the sampling (PG PDF 477-478,
    printed 4-159 to 4-160).

    Forces ``base`` from the trigger and ``bias`` after ``h_base`` (``MT``) until the end; ``vrange`` from Table 4-4
    (PDF 339; 0 auto, positive limited auto: the instrument picks the smallest range covering base and bias). Icomp
    is always sent (0 A is not allowed). Clears, and is cleared by, ``MI`` on the channel; a ``DV`` on the same
    channel makes it a plain DC source.
    """
    _choice(vrange, V_RANGE_CODES, "MV vrange")
    _finite(base, "MV base")
    _finite(bias, "MV bias")
    if _finite(icomp, "MV Icomp") == 0:
        raise ValueError("MV Icomp must not be 0 A (PG PDF 478)")
    return f"MV {_channel(ch)},{vrange},{_num(base)},{_num(bias)},{_num(icomp)}"


def mi(ch: int, irange: int, base: float, bias: float, vcomp: float) -> str:
    """``MI chnum,irange,base,bias,Vcomp``: SMU current source synchronized with the sampling (PG PDF 468-469,
    printed 4-150 to 4-151).

    Same timing as ``MV``; ``irange`` from Table 4-5 (PDF 340; 0 auto, positive limited auto); ``base`` and ``bias``
    must have the same polarity (zero allowed); Vcomp is always sent. Clears, and is cleared by, ``MV``.
    """
    _choice(irange, frozenset(I_RANGE_CODES), "MI irange")
    base, bias = _finite(base, "MI base"), _finite(bias, "MI bias")
    if base * bias < 0:
        raise ValueError(f"MI base and bias must have the same polarity (PG PDF 469), got {base} and {bias}")
    _finite(vcomp, "MI Vcomp")
    return f"MI {_channel(ch)},{irange},{_num(base)},{_num(bias)},{_num(vcomp)}"
