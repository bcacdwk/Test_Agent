"""SMU quasi-static C-V FLEX builders (``MM 13``): ``QSV``, ``QST``, ``QSM``, ``QSL``, ``QSO``, ``QSC``, ``QSR``,
``QSZ`` (blueprint v2 2.5, 2.7 kind ``smu_qscv``, WP8.5).

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). Source: Keysight B1500 Series
Programming Guide, Edition 15 ("PG"); chapter 4 printed page 4-N is PDF page N + 318.

Operation (PG p115-117 (2-27 to 2-29); programming example Table 3-17, p241-245 (3-61 to 3-65)): the ``QSV`` source
sweeps from ``start`` to ``stop`` (and back with mode 3) and measures at every sweep step except start and stop; at
step N it forces ``V_N - cvoltage/2``, waits ``delay1``, measures the leakage ``IL0`` (``linteg``) and ``V0``, then
the charge current ``I`` and the average voltage ``Vavg`` during the transition to ``V_N + cvoltage/2`` (``cinteg``),
then ``IL`` and ``V``, and waits ``delay2``. ``C = (I - Leak) x cinteg / (V - V0)`` with ``Leak = IL0 + (IL - IL0)
(Vavg - V0) / (V - V0)`` (normal mode, ``QSC 0``) or ``IL + tau (IL0 - IL) / (2 cinteg)`` (4155C/4156C compatible,
``QSC 1``); ``QSL x,0`` drops the compensation (``C = I x cinteg / (V - V0)``). When ``|step voltage| = cvoltage``
the next step starts where the last one ended: ``delay2`` is 0 and ``V0``/``IL0`` of the previous step are reused.

Data (PG p49 (1-29)): one block per measured step, ``[DataL,] DataC [,Source_data]``: the leakage current (data type
``I``, with ``QSL 1,x``), the capacitance (data type ``C``) and the sweep output (``FMT`` mode 1). ``QSZ 2`` measures
the capacitance offset of the path (terminals open at the device end) and returns one ``C`` datum; ``QSZ 1`` then
subtracts it from every datum. Errors 240-247 (PG p580-581 (5-8 to 5-9)).
"""

from __future__ import annotations

import math
from typing import Final

from b1500_test_agent.driver.flex.core import _channel, _choice, _num
from b1500_test_agent.driver.flex.smu import V_RANGE_CODES

QSCV_MODE: Final = 13
"""``MM 13[,chnum]``: quasi-static C-V; without a channel the ``QSV`` channel measures (Table 4-28, PG PDF 471; QSV
p497 (4-179))."""

QSCV_SWEEP_MODES: Final[dict[str, int]] = {"single": 1, "double": 3}
"""``QSV`` mode: 1 linear single stair (start to stop), 3 linear double stair (start to stop to start) (PG p498
(4-180); error 246 for anything else)."""

QSCV_MAX_STEPS: Final = 1001
"""``QSV`` step: the number of sweep steps, 1 to 1001 (PG p498 (4-180)); ``step = |start - stop| / |sweep step
voltage| - 1`` (start and stop are not measured)."""

QSCV_MAX_V: Final = 100.0
"""``QSV`` start/stop: 0 to +/-100 V for MP/HRSMU (PG p498 (4-180), Table 4-7); the module limits are
``driver/modules.py``'s and the hard ceiling the rules'."""

QSCV_MAX_CVOLTAGE_V: Final = 10.0
"""``QSV`` cvoltage: at most 10 V and at least twice the output resolution; the instrument reduces a value above
``|sweep step voltage|`` to it (PG p498 (4-180))."""

QSCV_RANGE_CODES: Final[dict[int, float]] = {-9: 1e-11, -10: 1e-10, -11: 1e-9, -12: 1e-8, -13: 1e-7, -14: 1e-6}
"""``QSR`` fixed current measurement range code -> full scale (A): 10 pA to 1 uA, initial -11 (1 nA) (PG p496
(4-178); error 241). The range serves the leakage and the capacitance measurement."""

QSCV_POST: Final[dict[str, int]] = {"start": 1, "stop": 2}
"""``QSM`` post: the sweep source value after a normal end, 1 start (initial), 2 stop (PG p494-495 (4-176 to
4-177)); after an automatic abort the source forces start."""

QSCV_ABORT: Final[dict[bool, int]] = {False: 1, True: 2}
"""``QSM`` abort: 1 disabled (initial), 2 enabled (compliance, ADC overflow, oscillation) (PG p494 (4-176))."""

QSCV_OPERATION: Final[dict[str, int]] = {"normal": 0, "compatible": 1}
"""``QSC`` mode: 0 normal (initial), 1 4155C/4156C compatible (PG p493 (4-175))."""

QSZ_OFF: Final = 0
QSZ_ON: Final = 1
QSZ_MEASURE: Final = 2
"""``QSZ`` mode: 0 offset cancel off (initial), 1 on, 2 measure the offset and return it (does not switch the cancel
on) (PG p499-500 (4-181 to 4-182)); the QSCV setup must be complete and ``MM 13`` sent first (error 243)."""

LINE_FREQUENCIES_HZ: Final = (50.0, 60.0)
"""Power-line frequencies ``QST`` rounds the integration times to (``n / line frequency``)."""

QST_CINTEG_S: Final = (1.0 / 60.0, 400.0)
"""``QST`` cinteg: 0.02-400 s at 50 Hz, 0.016667-333.33 s at 60 Hz, rounded to ``n / f_line`` (n = 1-20000);
initial 5 / f_line (PG p496-497 (4-178 to 4-179))."""

QST_LINTEG_S: Final = (1.0 / 60.0, 2.0)
"""``QST`` linteg: 0.02-2 s at 50 Hz, 0.016667-1.6667 s at 60 Hz, ``n / f_line`` (n = 1-100); initial 5 / f_line
(PG p497 (4-179))."""

QST_MAX_HOLD_S: Final = 655.35
QST_HOLD_RESOLUTION_S: Final = 0.01
QST_MAX_DELAY_S: Final = 65.535
QST_DELAY_RESOLUTION_S: Final = 1e-4
"""``QST`` hold 0-655.35 s (10 ms resolution), delay1/delay2 0-65.535 s (0.1 ms) (PG p497 (4-179))."""

QST_N_LIMITS: Final = {"cinteg": 20000, "linteg": 100}
"""Largest integration-time multiple ``n`` of the line period (PG p496-497)."""


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


def qsv(ch: int, mode: str, vrange: int, start: float, stop: float, cvoltage: float, steps: int,
        icomp: float) -> str:
    """``QSV chnum,mode,vrange,start,stop,cvoltage,step,Icomp``: the QSCV voltage sweep source (PG PDF 497-499, printed
    4-179 to 4-181). ``mode`` ``single``/``double``; ``vrange`` a voltage output ranging code (Table 4-4: the minimum
    range covering start and stop, never below a limited one); start and stop different, within +/-100 V; ``cvoltage``
    > 0 and at most 10 V (the instrument reduces it to ``|sweep step voltage|``); ``steps`` 1-1001 (``|start - stop| /
    |sweep step voltage| - 1``); Icomp always sent and not 0 A (its polarity follows the output)."""
    if mode not in QSCV_SWEEP_MODES:
        raise ValueError(f"QSV mode must be 'single' or 'double', got {mode!r}")
    _choice(vrange, V_RANGE_CODES, "QSV range")
    start, stop = _finite(start, "QSV start"), _finite(stop, "QSV stop")
    if max(abs(start), abs(stop)) > QSCV_MAX_V:
        raise ValueError(f"QSV start/stop must be within +/-{QSCV_MAX_V:g} V, got {start:g}, {stop:g}")
    if start == stop:
        raise ValueError("QSV start and stop must be different")
    cvoltage = _finite(cvoltage, "QSV cvoltage")
    if not 0 < cvoltage <= QSCV_MAX_CVOLTAGE_V:
        raise ValueError(f"QSV cvoltage must be above 0 and at most {QSCV_MAX_CVOLTAGE_V:g} V, got {cvoltage:g}")
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= QSCV_MAX_STEPS:
        raise ValueError(f"QSV step must be an integer 1 to {QSCV_MAX_STEPS}, got {steps!r}")
    icomp = _finite(icomp, "QSV Icomp")
    if icomp == 0:
        raise ValueError("QSV Icomp must not be 0 (it is always sent, never the previous value)")
    return (f"QSV {_channel(ch)},{QSCV_SWEEP_MODES[mode]},{vrange},{_num(start)},{_num(stop)},{_num(cvoltage)},"
            f"{steps},{_num(icomp)}")


def qst(cinteg: float, linteg: float, hold: float, delay1: float, delay2: float) -> str:
    """``QST cinteg,linteg,hold,delay1,delay2``: integration times of the capacitance and the leakage measurement
    (s; rounded by the instrument to ``n / line frequency``), the hold time before the first step's delay1 (0-655.35
    s, 10 ms steps) and the delays after each step's start (delay1) and end (delay2) (0-65.535 s, 0.1 ms steps) (PG
    PDF 496-497, printed 4-178 to 4-179). ``delay2`` is always sent."""
    cinteg, linteg = _finite(cinteg, "QST cinteg"), _finite(linteg, "QST linteg")
    if not QST_CINTEG_S[0] - 1e-9 <= cinteg <= QST_CINTEG_S[1]:
        raise ValueError(f"QST cinteg must be {QST_CINTEG_S[0]:.6g} to {QST_CINTEG_S[1]:g} s, got {cinteg:g}")
    if not QST_LINTEG_S[0] - 1e-9 <= linteg <= QST_LINTEG_S[1]:
        raise ValueError(f"QST linteg must be {QST_LINTEG_S[0]:.6g} to {QST_LINTEG_S[1]:g} s, got {linteg:g}")
    hold = _finite(hold, "QST hold")
    if not 0 <= hold <= QST_MAX_HOLD_S or not _on_grid(hold, QST_HOLD_RESOLUTION_S):
        raise ValueError(f"QST hold must be 0 to {QST_MAX_HOLD_S} s in 10 ms steps, got {hold}")
    for name, value in (("delay1", delay1), ("delay2", delay2)):
        value = _finite(value, f"QST {name}")
        if not 0 <= value <= QST_MAX_DELAY_S or not _on_grid(value, QST_DELAY_RESOLUTION_S):
            raise ValueError(f"QST {name} must be 0 to {QST_MAX_DELAY_S} s in 0.1 ms steps, got {value}")
    return f"QST {_num(cinteg)},{_num(linteg)},{_num(hold)},{_num(delay1)},{_num(delay2)}"


def qsm(abort: bool, post: str) -> str:
    """``QSM abort,post``: automatic abort (``True``: compliance on any channel, ADC overflow or oscillation stops the
    measurement, the source forces start) and the source value after a normal end (``start``/``stop``)
    (PG PDF 494-495, printed 4-176 to 4-177). Both values are always sent."""
    if not isinstance(abort, bool):
        raise TypeError(f"QSM abort must be a bool, got {abort!r}")
    if post not in QSCV_POST:
        raise ValueError(f"QSM post must be 'start' or 'stop', got {post!r}")
    return f"QSM {QSCV_ABORT[abort]},{QSCV_POST[post]}"


def qsl(data: bool, compensation: bool) -> str:
    """``QSL data,compen``: leakage current data output and leakage current compensation on (``True``) or off (PG
    PDF 493-494, printed 4-175 to 4-176); ``QSL 0,0`` skips the leakage measurement."""
    if not isinstance(data, bool) or not isinstance(compensation, bool):
        raise TypeError(f"QSL takes two bools, got {data!r}, {compensation!r}")
    return f"QSL {int(data)},{int(compensation)}"


def qso(on: bool, ch: int | None = None, vcomp: float | None = None) -> str:
    """``QSO mode[,chnum[,Vcomp]]``: the QSCV smart operation (PG PDF 495, printed 4-177): off (``QSO 0``, initial)
    or on with the dedicated SMU ``ch`` (another channel than the measurement and sweep channels, error 247) that
    forces a current to cancel an offset current, voltage compliance ``vcomp`` (V). Needs ``QSC 0``. With ``on`` false
    no channel may be given."""
    if not isinstance(on, bool):
        raise TypeError(f"QSO mode must be a bool, got {on!r}")
    if not on:
        if ch is not None or vcomp is not None:
            raise ValueError("QSO 0 takes no channel or compliance (PG p495)")
        return "QSO 0"
    if ch is None:
        raise ValueError("QSO 1 needs the dedicated SMU channel (error 247)")
    text = f"QSO 1,{_channel(ch)}"
    if vcomp is not None:
        vcomp = _finite(vcomp, "QSO Vcomp")
        if vcomp == 0:
            raise ValueError("QSO Vcomp must not be 0")
        text += f",{_num(vcomp)}"
    return text


def qsc(operation: str) -> str:
    """``QSC mode``: the QSCV operation, ``normal`` (0, initial) or ``compatible`` (1, 4155C/4156C compatible: good
    for low leakage or a low QSCV measurement voltage) (PG PDF 493, printed 4-175)."""
    if operation not in QSCV_OPERATION:
        raise ValueError(f"QSC operation must be 'normal' or 'compatible', got {operation!r}")
    return f"QSC {QSCV_OPERATION[operation]}"


def qsr(code: int) -> str:
    """``QSR range``: the fixed current measurement range of the leakage and capacitance measurements, -9 (10 pA) to
    -14 (1 uA), initial -11 (1 nA) (PG PDF 496, printed 4-178; error 241)."""
    return f"QSR {_choice(code, QSCV_RANGE_CODES, 'QSR range')}"


def qsz(mode: int) -> str:
    """``QSZ mode``: capacitance offset cancel off (0, initial) or on (1), or 2: measure the offset with the
    measurement terminals open at the device end and return it (one data element; it does not switch the cancel on)
    (PG PDF 499-500, printed 4-181 to 4-182). Needs the QSCV setup and ``MM 13`` first (error 243)."""
    return f"QSZ {_choice(mode, (QSZ_OFF, QSZ_ON, QSZ_MEASURE), 'QSZ mode')}"


__all__ = [
    "LINE_FREQUENCIES_HZ", "QSCV_ABORT", "QSCV_MAX_CVOLTAGE_V", "QSCV_MAX_STEPS", "QSCV_MAX_V", "QSCV_MODE",
    "QSCV_OPERATION", "QSCV_POST", "QSCV_RANGE_CODES", "QSCV_SWEEP_MODES", "QST_CINTEG_S", "QST_DELAY_RESOLUTION_S",
    "QST_HOLD_RESOLUTION_S", "QST_LINTEG_S", "QST_MAX_DELAY_S", "QST_MAX_HOLD_S", "QST_N_LIMITS", "QSZ_MEASURE",
    "QSZ_OFF", "QSZ_ON", "qsc", "qsl", "qsm", "qso", "qsr", "qst", "qsv",
    "qsz",
]
