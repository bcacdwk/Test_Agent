"""SMU search and quasi-pulsed FLEX builders (``MM 14`` linear search, ``MM 15`` binary search, ``MM 9`` quasi-pulsed
spot): ``LSV``, ``LSI``, ``LGV``, ``LGI``, ``LSM``, ``LSTM``, ``LSSV``, ``LSSI``, ``LSVM``, ``BSV``, ``BSI``, ``BGV``,
``BGI``, ``BSM``, ``BST``, ``BSSV``, ``BSSI``, ``BSVM``, ``BDV``, ``BDT``, ``BDM`` (blueprint v2 2.5, 2.7 kind
``smu_search``, WP7.5).

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). The search commands live in their
own module (not ``smu.py``) so the SMU measurement-mode work packages touch disjoint files. Source: Keysight B1500
Series Programming Guide, Edition 15 ("PG"); chapter 4 printed page 4-N is PDF page N + 318.

Operation (PG PDF 106-111, printed 2-18 to 2-23; programming examples p216-223, printed 3-36 to 3-43):

- ``MM 14`` linear search: the search source (``LSV``/``LSI``: start, stop, step) steps from start towards stop; after
  the hold time (``LSTM``) and the delay of each step the monitor channel (``LGI``/``LGV``) measures once; the search
  stops at the first step whose measured value is ``<= target`` (mode 0) or ``>= target`` (mode 1). At most 1001
  steps (p460, printed 4-142).
- ``MM 15`` binary search: the source (``BSV``/``BSI``: start, stop) halves its output change each time (``BSM``:
  normal mode forces start, then stop, then stop -/+ D/2 ...; cautious mode start, then start +/- D/2 ...) until the
  monitor (``BGI``/``BGV``) reads ``target +/- condition`` (limit mode 0) or the output changed more than
  ``condition`` times (repeat mode 1, 1-16; p366-368).
- Both: an optional synchronous source (``LSSV``/``LSSI``, ``BSSV``/``BSSI``: ``polarity x search + offset``, same
  output mode and range as the search source, sent after it: ``LSV``/``LSI``/``BSV``/``BSI`` clear it); ``LSM``/
  ``BSM`` enable the automatic abort (compliance, overflow, oscillation: the sources force their start values) and
  choose the output after a normal end (start, stop or the value at the target); ``LSVM``/``BSVM`` 1 returns
  ``Data_search,Data_sense`` (the forced value at the measurement point closest to the target and the monitor's
  reading; p47, printed 1-27). The monitor measures its compliance side (``LGI``/``BGI`` on a voltage source,
  ``LGV``/``BGV`` on a current source; error 279) and the target must not exceed its compliance (error 275, p582).
- ``MM 9`` quasi-pulsed spot (``BDV``, ``BDT``, ``BDM``): after the hold time the source sweeps from start towards stop
  while it detects settling; when the slew rate falls to half (near stop, or at its current compliance when the device
  breaks down) it keeps the output, waits the delay and the measurement channel measures once (voltage or current,
  ``BDM`` mode); then the source returns to start. ``|start - stop|`` must be 10 V or more (p107, printed 2-19); a
  compliance before a 10 V change from start reads status ``S``, a detection time above 3 s (short) / 12 s (long)
  status ``G`` (Table 1-10, p53, printed 1-33).

Data status (Table 1-10, p53; ``EEE`` 16/32 in FMT 21/25, Table 1-8 p52): ``G`` target not found in the search range
(the source value is returned), ``S`` search stopped by the automatic abort (see ``Data_sense``'s status). The time
stamp function is not available for MM 9, 14, 15 (TSC p538, printed 4-220).
"""

from __future__ import annotations

import math

from b1500_test_agent.driver.flex.core import _channel, _choice, _num
from b1500_test_agent.driver.flex.smu import I_OUTPUT_RANGE_CODES, I_RANGE_CODES, V_RANGE_CODES

# -- Measurement modes -------------------------------------------------------------------------------------------

QUASI_PULSED_SPOT_MODE = 9
"""``MM 9[,chnum]``: quasi-pulsed spot measurement (Table 4-28, PG PDF 471; operation p106-107)."""

LINEAR_SEARCH_MODE = 14
"""``MM 14``: linear search measurement, no channel list (Table 4-28, PG PDF 471; operation p110-111)."""

BINARY_SEARCH_MODE = 15
"""``MM 15``: binary search measurement, no channel list (Table 4-28, PG PDF 471; operation p108-109)."""

SEARCH_MODES = frozenset({QUASI_PULSED_SPOT_MODE, LINEAR_SEARCH_MODE, BINARY_SEARCH_MODE})
"""The SMU search measurement modes of kind ``smu_search`` (MM syntax PG PDF 470)."""

# -- Parameter domains -------------------------------------------------------------------------------------------

SEARCH_MAX_HOLD_S = 655.35
SEARCH_HOLD_RESOLUTION_S = 0.01
"""``LSTM``/``BST``/``BDT`` hold time: 0 to 655.35 s, 10 ms resolution (PG PDF 459, p374, p365)."""

SEARCH_MAX_DELAY_S = 65.535
"""``LSTM``/``BST`` delay: 0 to 65.535 s, 0.1 ms resolution (PG PDF 459, p374)."""

BDT_MAX_DELAY_S = 6.5535
SEARCH_DELAY_RESOLUTION_S = 1e-4
"""``BDT`` delay: 0 to 6.5535 s; every search delay has 0.1 ms resolution (PG PDF 365, p374, p459)."""

LINEAR_SEARCH_MAX_STEPS = 1001
"""Most search steps of ``LSV``/``LSI`` (PG PDF 460, p454)."""

BDV_MIN_SPAN_V = 10.0
"""``BDV``: ``|start - stop|`` must be 10 V or more (PG PDF 365, p107)."""

SMU_SEARCH_MAX_V = 100.0
SMU_SEARCH_MAX_I = 0.1
"""Syntax domain of search levels and targets over the MP/HRSMU (PG PDF 365, p367-368; the HPSMU's 200 V/1 A are not
driven by this station; module limits are ``driver/modules.py``'s)."""

LINEAR_JUDGE: dict[str, int] = {"below": 0, "above": 1}
"""``LGI``/``LGV`` mode: 0 = the result is the first step whose measured value is ``<= target``, 1 = ``>= target``
(PG PDF 443-444)."""

BINARY_LIMIT_MODE = 0
BINARY_REPEAT_MODE = 1
BINARY_MAX_REPEAT = 16
"""``BGI``/``BGV`` mode 0 = limit (stop at ``target +/- condition``), 1 = repeat count 1-16 (PG PDF 366, p368)."""

BINARY_CONTROL: dict[str, int] = {"normal": 0, "cautious": 1}
"""``BSM`` output control mode (PG PDF 370-372, Figure 4-2)."""

SEARCH_ABORT: dict[bool, int] = {False: 1, True: 2}
"""``LSM``/``BSM`` automatic abort: 1 disabled (initial setting), 2 enabled (PG PDF 454-455, p370)."""

SEARCH_POST: dict[str, int] = {"start": 1, "stop": 2, "last": 3}
"""``LSM``/``BSM`` output after a normal end: 1 start (initial), 2 stop, 3 the value at the target (PG PDF 455,
p370)."""

SEARCH_SYNC_POLARITY: dict[int, int] = {-1: 0, 1: 1}
"""``LSSV``/``LSSI``/``BSSV``/``BSSI`` polarity: 0 negative (``-search + offset``), 1 positive (PG PDF 455-456,
372)."""

BDM_INTERVALS: dict[str, int] = {"short": 0, "long": 1}
"""``BDM`` settling detection interval: 0 short (initial; needs > 1 V/ms and detection <= 3 s), 1 long (stray
capacitance or compliance below 1 uA; > 0.1 V/ms, <= 12 s) (PG PDF 364)."""

BDM_MODES: dict[str, int] = {"V": 0, "I": 1}
"""``BDM`` measurement mode: 0 voltage (default), 1 current (PG PDF 364)."""


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


def _timing(hold: float, delay: float, name: str, max_delay: float) -> tuple[float, float]:
    hold, delay = _finite(hold, f"{name} hold"), _finite(delay, f"{name} delay")
    if not 0 <= hold <= SEARCH_MAX_HOLD_S or not _on_grid(hold, SEARCH_HOLD_RESOLUTION_S):
        raise ValueError(f"{name} hold must be 0 to {SEARCH_MAX_HOLD_S} s in 10 ms steps, got {hold}")
    if not 0 <= delay <= max_delay or not _on_grid(delay, SEARCH_DELAY_RESOLUTION_S):
        raise ValueError(f"{name} delay must be 0 to {max_delay} s in 0.1 ms steps, got {delay}")
    return hold, delay


def _comp(value: float, name: str) -> float:
    if _finite(value, name) == 0:
        raise ValueError(f"{name} must not be 0 (it is always sent, never the previous value)")
    return float(value)


def _level(value: float, name: str, *, current: bool) -> float:
    value = _finite(value, name)
    limit = SMU_SEARCH_MAX_I if current else SMU_SEARCH_MAX_V
    if abs(value) > limit:
        raise ValueError(f"{name} must be within +/-{limit:g} {'A' if current else 'V'}, got {value}")
    return value


def _start_stop(start: float, stop: float, name: str, *, current: bool) -> tuple[float, float]:
    start = _level(start, f"{name} start", current=current)
    stop = _level(stop, f"{name} stop", current=current)
    if start == stop:
        raise ValueError(f"{name} start and stop must be different (error 276, PG PDF 582)")
    return start, stop


def _polarity(polarity: int, name: str) -> int:
    if isinstance(polarity, bool) or polarity not in SEARCH_SYNC_POLARITY:
        raise ValueError(f"{name} polarity must be +1 or -1, got {polarity!r}")
    return SEARCH_SYNC_POLARITY[polarity]


def _linear_steps(start: float, stop: float, step: float) -> int:
    """Number of search steps of ``LSV``/``LSI`` from ``start`` towards ``stop`` in ``step`` increments (the last
    step not beyond ``stop``): ``floor(|stop - start| / |step|) + 1``."""
    return math.floor(abs(stop - start) / abs(step) + 1e-9) + 1


def _linear(start: float, stop: float, step: float, name: str, *, current: bool) -> tuple[float, float, float]:
    start, stop = _start_stop(start, stop, name, current=current)
    step = _finite(step, f"{name} step")
    if step == 0 or (step > 0) != (stop > start):
        raise ValueError(f"{name} step must be non-zero and point from start to stop (PG PDF 460), got {step}")
    if _linear_steps(start, stop, step) > LINEAR_SEARCH_MAX_STEPS:
        raise ValueError(f"{name}: at most {LINEAR_SEARCH_MAX_STEPS} search steps (PG PDF 460), got "
                         f"{_linear_steps(start, stop, step)}")
    return start, stop, step


# -- Linear search (MM 14) -----------------------------------------------------------------------------------------


def lstm(hold: float, delay: float) -> str:
    """``LSTM hold,delay``: hold time (0-655.35 s, 10 ms steps; before the delay of the first step) and delay (0-65.535
    s, 0.1 ms steps; after each step's output change, before its measurement) of the linear search (PG PDF 459, printed
    4-141)."""
    hold, delay = _timing(hold, delay, "LSTM", SEARCH_MAX_DELAY_S)
    return f"LSTM {_num(hold)},{_num(delay)}"


def lsm(abort: bool, post: str) -> str:
    """``LSM abort,post``: automatic abort of the linear search (``True``: compliance, overflow or oscillation stops
    the search and the sources force their start values) and the output after a normal end (``start``, ``stop`` or
    ``last``: the value at the target) (PG PDF 454-455, printed 4-136 to 4-137). Both values are always sent."""
    if not isinstance(abort, bool):
        raise TypeError(f"LSM abort must be a bool, got {abort!r}")
    return f"LSM {SEARCH_ABORT[abort]},{SEARCH_POST[_post(post, 'LSM')]}"


def lsvm(sense: bool) -> str:
    """``LSVM mode``: data output of the linear search, 0 ``Data_search`` only (initial), 1 ``Data_search,Data_sense``
    (PG PDF 460, printed 4-142)."""
    if not isinstance(sense, bool):
        raise TypeError(f"LSVM takes a bool, got {sense!r}")
    return f"LSVM {1 if sense else 0}"


def lgi(ch: int, judge: str, irange: int, target: float) -> str:
    """``LGI chnum,mode,range,target``: current monitor of the linear search (PG PDF 443, printed 4-125). ``judge``
    ``below`` (mode 0: the result is the first step with ``I <= target``) or ``above`` (mode 1: ``I >= target``);
    ``irange`` a current ranging code of Table 4-3 (0 auto or limited auto, the minimum range covering the target);
    ``target`` in A within +/-0.1 A (MP/HRSMU). Clears ``LGV``; ignores ``RI``."""
    return _monitor_linear("LGI", ch, judge, irange, target, current=True)


def lgv(ch: int, judge: str, vrange: int, target: float) -> str:
    """``LGV chnum,mode,range,target``: voltage monitor of the linear search (PG PDF 444, printed 4-126); ``judge`` as
    ``LGI``, ``vrange`` a voltage ranging code of Table 4-2, ``target`` in V within +/-100 V (MP/HRSMU). Clears
    ``LGI``; ignores ``RV``."""
    return _monitor_linear("LGV", ch, judge, vrange, target, current=False)


def _monitor_linear(mnemonic: str, ch: int, judge: str, rng: int, target: float, *, current: bool) -> str:
    if judge not in LINEAR_JUDGE:
        raise ValueError(f"{mnemonic} judge must be 'below' or 'above', got {judge!r}")
    _choice(rng, I_RANGE_CODES if current else V_RANGE_CODES, f"{mnemonic} range")
    target = _level(target, f"{mnemonic} target", current=current)
    return f"{mnemonic} {_channel(ch)},{LINEAR_JUDGE[judge]},{rng},{_num(target)}"


def lsv(ch: int, vrange: int, start: float, stop: float, step: float, icomp: float) -> str:
    """``LSV chnum,range,start,stop,step,Icomp``: voltage search source of the linear search (PG PDF 459-460, printed
    4-141 to 4-142). ``vrange`` from Table 4-4 (the minimum range covering start and stop; a range change may output
    0 V for a moment); start and stop different, within +/-100 V; ``step`` points from start to stop, at most 1001
    steps; Icomp always sent and not 0 A. Clears ``LSI``, ``LSSI``, ``LSSV``."""
    _choice(vrange, V_RANGE_CODES, "LSV range")
    start, stop, step = _linear(start, stop, step, "LSV", current=False)
    icomp = _comp(icomp, "LSV Icomp")
    return f"LSV {_channel(ch)},{vrange},{_num(start)},{_num(stop)},{_num(step)},{_num(icomp)}"


def lsi(ch: int, irange: int, start: float, stop: float, step: float, vcomp: float) -> str:
    """``LSI chnum,range,start,stop,step,Vcomp``: current search source of the linear search (PG PDF 453-454, printed
    4-135 to 4-136); ``irange`` from Table 4-5, start and stop within +/-0.1 A, ``step`` as ``LSV``; Vcomp always sent
    and not 0 V. Clears ``LSV``, ``LSSI``, ``LSSV``."""
    _choice(irange, I_OUTPUT_RANGE_CODES, "LSI range")
    start, stop, step = _linear(start, stop, step, "LSI", current=True)
    vcomp = _comp(vcomp, "LSI Vcomp")
    return f"LSI {_channel(ch)},{irange},{_num(start)},{_num(stop)},{_num(step)},{_num(vcomp)}"


def lssv(ch: int, polarity: int, offset: float, icomp: float) -> str:
    """``LSSV chnum,polarity,offset,Icomp``: synchronous voltage source of the linear search, ``polarity x LSV output
    + offset`` (``polarity`` +1 or -1; PG PDF 456-457, printed 4-138 to 4-139). Sent after ``LSV``, on another channel;
    both use the search source's output range. Icomp always sent and not 0 A."""
    return _sync("LSSV", ch, polarity, offset, icomp, current=False)


def lssi(ch: int, polarity: int, offset: float, vcomp: float) -> str:
    """``LSSI chnum,polarity,offset,Vcomp``: synchronous current source of the linear search, ``polarity x LSI output
    + offset`` (PG PDF 455-456, printed 4-137 to 4-138). Sent after ``LSI``; Vcomp always sent and not 0 V."""
    return _sync("LSSI", ch, polarity, offset, vcomp, current=True)


def _sync(mnemonic: str, ch: int, polarity: int, offset: float, comp: float, *, current: bool) -> str:
    code = _polarity(polarity, mnemonic)
    offset = _level(offset, f"{mnemonic} offset", current=current)
    comp = _comp(comp, f"{mnemonic} compliance")
    return f"{mnemonic} {_channel(ch)},{code},{_num(offset)},{_num(comp)}"


# -- Binary search (MM 15) -----------------------------------------------------------------------------------------


def bst(hold: float, delay: float) -> str:
    """``BST hold,delay``: hold time (0-655.35 s, 10 ms steps) and delay (0-65.535 s, 0.1 ms steps) of the binary
    search (PG PDF 374, printed 4-56)."""
    hold, delay = _timing(hold, delay, "BST", SEARCH_MAX_DELAY_S)
    return f"BST {_num(hold)},{_num(delay)}"


def bsm(control: str, abort: bool, post: str) -> str:
    """``BSM mode,abort,post``: output control (``normal``: start, stop, then halving from stop; ``cautious``: start,
    start +/- D/2, then halving), automatic abort and the output after a normal end (``start``, ``stop``, ``last``)
    of the binary search (PG PDF 370-372, printed 4-52 to 4-54). All three values are always sent."""
    if control not in BINARY_CONTROL:
        raise ValueError(f"BSM control must be 'normal' or 'cautious', got {control!r}")
    if not isinstance(abort, bool):
        raise TypeError(f"BSM abort must be a bool, got {abort!r}")
    return f"BSM {BINARY_CONTROL[control]},{SEARCH_ABORT[abort]},{SEARCH_POST[_post(post, 'BSM')]}"


def bsvm(sense: bool) -> str:
    """``BSVM mode``: data output of the binary search, 0 ``Data_search`` only (initial), 1 ``Data_search,Data_sense``
    (PG PDF 375, printed 4-57)."""
    if not isinstance(sense, bool):
        raise TypeError(f"BSVM takes a bool, got {sense!r}")
    return f"BSVM {1 if sense else 0}"


def bgi(ch: int, mode: int, condition: float, irange: int, target: float) -> str:
    """``BGI chnum,mode,condition,range,target``: current monitor of the binary search (PG PDF 366-367, printed 4-48 to
    4-49). ``mode`` 0 (limit: ``condition`` > 0 A, the search stops at ``target +/- condition``; resolution
    range/20000) or 1 (repeat: ``condition`` = 1-16 output changes); ``irange`` from Table 4-3; ``target`` in A within
    +/-0.1 A. Clears ``BGV``; ignores ``RI``."""
    return _monitor_binary("BGI", ch, mode, condition, irange, target, current=True)


def bgv(ch: int, mode: int, condition: float, vrange: int, target: float) -> str:
    """``BGV chnum,mode,condition,range,target``: voltage monitor of the binary search (PG PDF 367-369, printed 4-49 to
    4-51); ``mode``/``condition`` as ``BGI`` (limit in V), ``vrange`` from Table 4-2, ``target`` within +/-100 V.
    Clears ``BGI``; ignores ``RV``."""
    return _monitor_binary("BGV", ch, mode, condition, vrange, target, current=False)


def _monitor_binary(mnemonic: str, ch: int, mode: int, condition: float, rng: int, target: float, *,
                    current: bool) -> str:
    _choice(mode, (BINARY_LIMIT_MODE, BINARY_REPEAT_MODE), f"{mnemonic} mode")
    if mode == BINARY_LIMIT_MODE:
        condition = _finite(condition, f"{mnemonic} limit")
        if condition <= 0:
            raise ValueError(f"{mnemonic} limit (mode 0) must be positive, got {condition}")
        cond_text = _num(condition)
    else:
        if isinstance(condition, bool) or not isinstance(condition, int | float) or condition != int(condition) \
                or not 1 <= int(condition) <= BINARY_MAX_REPEAT:
            raise ValueError(f"{mnemonic} repeat count (mode 1) must be 1 to {BINARY_MAX_REPEAT}, got {condition!r}")
        cond_text = str(int(condition))
    _choice(rng, I_RANGE_CODES if current else V_RANGE_CODES, f"{mnemonic} range")
    target = _level(target, f"{mnemonic} target", current=current)
    return f"{mnemonic} {_channel(ch)},{mode},{cond_text},{rng},{_num(target)}"


def bsv(ch: int, vrange: int, start: float, stop: float, icomp: float) -> str:
    """``BSV chnum,range,start,stop,Icomp``: voltage search source of the binary search (PG PDF 374-375, printed 4-56 to
    4-57); ``vrange`` from Table 4-4, start and stop different within +/-100 V, Icomp always sent and not 0 A. Clears
    ``BSI``, ``BSSI``, ``BSSV``."""
    _choice(vrange, V_RANGE_CODES, "BSV range")
    start, stop = _start_stop(start, stop, "BSV", current=False)
    icomp = _comp(icomp, "BSV Icomp")
    return f"BSV {_channel(ch)},{vrange},{_num(start)},{_num(stop)},{_num(icomp)}"


def bsi(ch: int, irange: int, start: float, stop: float, vcomp: float) -> str:
    """``BSI chnum,range,start,stop,Vcomp``: current search source of the binary search (PG PDF 369, printed 4-51);
    ``irange`` from Table 4-5, start and stop different within +/-0.1 A, Vcomp always sent and not 0 V. Clears
    ``BSV``, ``BSSI``, ``BSSV``."""
    _choice(irange, I_OUTPUT_RANGE_CODES, "BSI range")
    start, stop = _start_stop(start, stop, "BSI", current=True)
    vcomp = _comp(vcomp, "BSI Vcomp")
    return f"BSI {_channel(ch)},{irange},{_num(start)},{_num(stop)},{_num(vcomp)}"


def bssv(ch: int, polarity: int, offset: float, icomp: float) -> str:
    """``BSSV chnum,polarity,offset,Icomp``: synchronous voltage source of the binary search, ``polarity x BSV output
    + offset`` (PG PDF 373-374, printed 4-55 to 4-56). Sent after ``BSV``; Icomp always sent and not 0 A."""
    return _sync("BSSV", ch, polarity, offset, icomp, current=False)


def bssi(ch: int, polarity: int, offset: float, vcomp: float) -> str:
    """``BSSI chnum,polarity,offset,Vcomp``: synchronous current source of the binary search, ``polarity x BSI output
    + offset`` (PG PDF 372-373, printed 4-54 to 4-55). Sent after ``BSI``; Vcomp always sent and not 0 V."""
    return _sync("BSSI", ch, polarity, offset, vcomp, current=True)


# -- Quasi-pulsed spot (MM 9) ---------------------------------------------------------------------------------------


def bdt(hold: float, delay: float) -> str:
    """``BDT hold,delay``: hold time (0-655.35 s, 10 ms steps) and delay (0-6.5535 s, 0.1 ms steps; after the settling
    detection, before the measurement) of the quasi-pulsed measurement (PG PDF 365, printed 4-47)."""
    hold, delay = _timing(hold, delay, "BDT", BDT_MAX_DELAY_S)
    return f"BDT {_num(hold)},{_num(delay)}"


def bdm(interval: str, mode: str) -> str:
    """``BDM interval,mode``: settling detection interval (``short``/``long``) and measurement mode (``V``/``I``) of the
    quasi-pulsed measurement (PG PDF 364, printed 4-46). Both values are always sent."""
    if interval not in BDM_INTERVALS:
        raise ValueError(f"BDM interval must be 'short' or 'long', got {interval!r}")
    if mode not in BDM_MODES:
        raise ValueError(f"BDM mode must be 'V' or 'I', got {mode!r}")
    return f"BDM {BDM_INTERVALS[interval]},{BDM_MODES[mode]}"


def bdv(ch: int, vrange: int, start: float, stop: float, icomp: float) -> str:
    """``BDV chnum,range,start,stop,Icomp``: quasi-pulsed voltage source (PG PDF 365-366, printed 4-47 to 4-48).
    ``vrange`` from Table 4-4 (the minimum range covering start and stop); start and stop within +/-100 V (MP/HRSMU)
    and ``|start - stop| >= 10 V``; Icomp always sent and not 0 A (its polarity follows stop; the instrument sets it).
    """
    _choice(vrange, V_RANGE_CODES, "BDV range")
    start, stop = _start_stop(start, stop, "BDV", current=False)
    if abs(stop - start) < BDV_MIN_SPAN_V - 1e-12:
        raise ValueError(f"BDV |start - stop| must be {BDV_MIN_SPAN_V:g} V or more (PG PDF 107, p365), got "
                         f"{abs(stop - start):g} V")
    icomp = _comp(icomp, "BDV Icomp")
    return f"BDV {_channel(ch)},{vrange},{_num(start)},{_num(stop)},{_num(icomp)}"


def _post(post: str, name: str) -> str:
    if post not in SEARCH_POST:
        raise ValueError(f"{name} post must be one of {sorted(SEARCH_POST)}, got {post!r}")
    return post


__all__ = [
    "BDM_INTERVALS", "BDM_MODES", "BDT_MAX_DELAY_S", "BDV_MIN_SPAN_V", "BINARY_CONTROL", "BINARY_LIMIT_MODE",
    "BINARY_MAX_REPEAT", "BINARY_REPEAT_MODE", "BINARY_SEARCH_MODE", "LINEAR_JUDGE", "LINEAR_SEARCH_MAX_STEPS",
    "LINEAR_SEARCH_MODE", "QUASI_PULSED_SPOT_MODE", "SEARCH_ABORT", "SEARCH_DELAY_RESOLUTION_S",
    "SEARCH_HOLD_RESOLUTION_S", "SEARCH_MAX_DELAY_S", "SEARCH_MAX_HOLD_S", "SEARCH_MODES", "SEARCH_POST",
    "SEARCH_SYNC_POLARITY", "SMU_SEARCH_MAX_I", "SMU_SEARCH_MAX_V", "bdm", "bdt", "bdv", "bgi", "bgv", "bsi", "bsm",
    "bssi", "bssv", "bst", "bsv", "bsvm", "lgi", "lgv", "lsi", "lsm", "lssi", "lssv", "lstm", "lsv",
    "lsvm",
]
