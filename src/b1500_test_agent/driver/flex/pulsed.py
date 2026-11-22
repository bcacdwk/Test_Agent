"""SMU pulsed-measurement FLEX builders (``MM 3``, ``4``, ``5``, ``27``, ``28``): ``PT``, ``PV``, ``PI``, ``PWV``,
``PWI``, ``MCPT``, ``MCPNT``, ``MCPNX``, ``MCPWS``, ``MCPWNX`` (blueprint v2 2.5, 2.7 kind ``smu_pulsed``).

Part of ``driver/flex/``, the only package that spells FLEX mnemonics in string literals; see ``core.py`` for the
conventions (one command per string, syntax-domain checks only, page citations). The pulsed commands live in their
own module (not ``smu.py``) so that the SMU measurement-mode work packages touch disjoint files. Source: Keysight B1500
Series Programming Guide, Edition 15 ("PG"); chapter 4 printed page 4-N is PDF page N + 318.

Pulsed operation (PG PDF 93-105, printed 2-5 to 2-17): a pulse source forces its base value, after the hold time a
pulse of ``width`` to its peak value once per ``period``; the measurement channels measure at the end of the pulse
with the pulsed-measurement ADC (``AIT 2,...``: used automatically by these modes, ``AAD`` is not needed, PDF 351).

- ``MM 3`` pulsed spot: one ``PV``/``PI`` source (timing ``PT``), one measurement channel, one pulse per ``XE``.
- ``MM 4`` pulsed sweep: one ``PWV``/``PWI`` source (base, start, stop, steps), optional synchronous ``WSV``/``WSI``
  source sent after it, automatic abort ``WM``; one measurement channel; one pulse per step.
- ``MM 5`` staircase sweep with pulsed bias: a ``WV``/``WI`` staircase and one ``PV``/``PI`` pulse source that
  pulses once per step; one measurement channel.
- ``MM 27`` multi-channel pulsed spot / ``MM 28`` multi-channel pulsed sweep: common timing ``MCPT``, per pulse
  channel ``MCPNT`` (delay, width), pulsed bias sources ``MCPNX``, pulsed sweep sources ``MCPWNX`` (MM 28, sweep mode
  and steps ``MCPWS``), staircase sources ``WNX`` (MM 28); up to ten channels measure in parallel. Source numbers
  ``N`` (1-10) and channels are unique over ``MCPNX``, ``MCPWNX`` and ``WNX``: a repeated one replaces the earlier
  setting (PDF 463, 467). On HR/MP/HPSMU the delay is 0 and every pulse width the same (Table 4-27, PDF 462).

Timing domains (PT PDF 486-487, MCPT PDF 464-465): hold 0-655.35 s in 10 ms steps; period 5 ms-5 s in 0.1 ms steps
with ``period >= width + 2 ms`` (width up to 100 ms) or ``width + 10 ms`` (longer widths); widths 10 us-2 s on the
finest (2 us) grid here, the per-module ranges and resolutions (HR/MP/HPSMU 500 us-2 s at 100 us) are
``driver/modules.py`` ``SMU_PULSE_SPECS`` (rule R-PULSE-01). The automatic periods (``0``, ``-1``) are never built:
the preview must show the period that runs.
"""

from __future__ import annotations

import math

from b1500_test_agent.driver.flex.core import _channel, _choice, _int, _num
from b1500_test_agent.driver.flex.smu import I_OUTPUT_RANGE_CODES, MAX_SWEEP_STEPS, SWEEP_SOURCE_MODES, V_RANGE_CODES

# -- Measurement modes -------------------------------------------------------------------------------------------

PULSED_SPOT_MODE = 3
"""``MM 3``: pulsed spot measurement (Table 4-28, PDF 471; operation PDF 93)."""

PULSED_SWEEP_MODE = 4
"""``MM 4``: pulsed sweep measurement (Table 4-28, PDF 471; operation PDF 100-101)."""

PULSED_BIAS_SWEEP_MODE = 5
"""``MM 5``: staircase sweep with pulsed bias (Table 4-28, PDF 471; operation PDF 98-99)."""

MULTI_PULSED_SPOT_MODE = 27
"""``MM 27``: multi-channel pulsed spot measurement (operation PDF 94-95; MM syntax PDF 470)."""

MULTI_PULSED_SWEEP_MODE = 28
"""``MM 28``: multi-channel pulsed sweep measurement (operation PDF 104-105; MM syntax PDF 470)."""

PULSED_MODES = frozenset({PULSED_SPOT_MODE, PULSED_SWEEP_MODE, PULSED_BIAS_SWEEP_MODE, MULTI_PULSED_SPOT_MODE,
                          MULTI_PULSED_SWEEP_MODE})
"""The SMU pulsed measurement modes (Table 4-28, PDF 471); 3, 4, 5 take one measurement channel, 27 and 28 up to ten
(MM syntax PDF 470)."""

PULSE_ADC = 2
"""``AIT`` type of the pulsed-measurement ADC: used automatically by every pulsed mode (AAD PDF 351, AIT PDF 357)."""

PULSE_ADC_TIME_MODE = 3
"""``AIT 2,3,N``: the pulsed-measurement ADC's measurement time N in seconds, 2 us to 20 ms in 2 us steps (Table
4-21, PDF 358-359)."""

# -- Timing domains ----------------------------------------------------------------------------------------------

PULSE_MAX_HOLD_S = 655.35
PULSE_HOLD_RESOLUTION_S = 0.01
"""``PT``/``MCPT`` hold time: 0 to 655.35 s, 10 ms resolution (PDF 486, 464)."""

PULSE_MIN_WIDTH_S = 1e-5
PULSE_MAX_WIDTH_S = 2.0
PULSE_WIDTH_GRID_S = 2e-6
"""Pulse width syntax domain over the SMU types: 10 us (MCSMU) to 2 s on the 2 us grid; HR/MP/HPSMU 500 us to 2 s
in 100 us steps (PT PDF 486, MCPNT Table 4-27 PDF 462; per-module checks in ``driver/modules.py``)."""

PULSE_MIN_PERIOD_S = 5e-3
PULSE_MAX_PERIOD_S = 5.0
PULSE_PERIOD_RESOLUTION_S = 1e-4
"""Pulse period: 5 ms to 5.0 s, 0.1 ms resolution (PT PDF 487, MCPT PDF 464); 0 and -1 (automatic) are never
built."""

PULSE_LONG_WIDTH_S = 0.1
PULSE_PERIOD_MARGIN_S = 2e-3
PULSE_PERIOD_MARGIN_LONG_S = 1e-2
"""``period >= width + 2 ms`` for widths up to 100 ms, ``>= width + 10 ms`` above (PT PDF 487; MCPT: ``t0 = delay +
width``, PDF 464)."""

TRIGGER_DELAY_RESOLUTION_S = 1e-4
"""``PT`` Tdelay (trigger output delay): 0 to width, 0.1 ms resolution (PDF 487)."""

MCPT_MEASURE_DELAY_GRID_S = 2e-6
"""``MCPT`` Mdelay: 2 us resolution; 0 = automatic (the measurement ends when the first pulse source starts its
transition back to base, PDF 464-465)."""

MCPT_MAX_AVERAGE = 1023
"""``MCPT`` average: measurements averaged per datum, 1 to 1023 (PDF 465)."""

MCP_MAX_SOURCE = 10
"""Source number ``N`` of ``MCPNX``, ``MCPWNX`` and ``WNX`` in MM 27/28: 1 to 10 (PDF 462, 465)."""


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _on_grid(value: float, step: float) -> bool:
    return abs(value / step - round(value / step)) < 1e-6


def _hold(hold: float, name: str) -> float:
    hold = _finite(hold, name)
    if not 0 <= hold <= PULSE_MAX_HOLD_S or not _on_grid(hold, PULSE_HOLD_RESOLUTION_S):
        raise ValueError(f"{name} must be 0 to {PULSE_MAX_HOLD_S} s in 10 ms steps, got {hold}")
    return hold


def _width(width: float, name: str) -> float:
    width = _finite(width, name)
    if not PULSE_MIN_WIDTH_S <= width <= PULSE_MAX_WIDTH_S or not _on_grid(width, PULSE_WIDTH_GRID_S):
        raise ValueError(f"{name} must be {PULSE_MIN_WIDTH_S} to {PULSE_MAX_WIDTH_S} s on the 2 us grid, got {width}")
    return width


def _period(period: float, t0: float, name: str) -> float:
    period = _finite(period, name)
    if not PULSE_MIN_PERIOD_S <= period <= PULSE_MAX_PERIOD_S or not _on_grid(period, PULSE_PERIOD_RESOLUTION_S):
        raise ValueError(f"{name} must be {PULSE_MIN_PERIOD_S} to {PULSE_MAX_PERIOD_S} s in 0.1 ms steps, got "
                         f"{period} (the automatic periods 0 and -1 are never built)")
    margin = PULSE_PERIOD_MARGIN_S if t0 <= PULSE_LONG_WIDTH_S else PULSE_PERIOD_MARGIN_LONG_S
    if period < t0 + margin - 1e-12:
        raise ValueError(f"{name} {period} s must be at least {t0:g} s + {margin * 1e3:g} ms")
    return period


def _comp(value: float, name: str) -> float:
    if _finite(value, name) == 0:
        raise ValueError(f"{name} must not be 0 (it is always sent, never the previous value)")
    return float(value)


def _same_polarity(values: tuple[float, ...], name: str) -> None:
    if any(v > 0 for v in values) and any(v < 0 for v in values):
        raise ValueError(f"{name} must have the same polarity, got {list(values)}")


def _source(source: str, name: str) -> int:
    if source not in SWEEP_SOURCE_MODES:
        raise ValueError(f"{name} source must be 'V' or 'I', got {source!r}")
    return SWEEP_SOURCE_MODES[source]


def _source_number(n: int, name: str) -> int:
    if _int(n, f"{name} N") not in range(1, MCP_MAX_SOURCE + 1):
        raise ValueError(f"{name} N must be 1 to {MCP_MAX_SOURCE}, got {n}")
    return n


def _sweep_mode(mode: int, name: str) -> int:
    return _choice(mode, (1, 2, 3, 4), f"{name} mode")


def _steps(points: int, name: str) -> int:
    if not 1 <= _int(points, f"{name} step") <= MAX_SWEEP_STEPS:
        raise ValueError(f"{name} step (number of points) must be 1 to {MAX_SWEEP_STEPS}, got {points}")
    return points


# -- Builders ------------------------------------------------------------------------------------------------------


def pt(hold: float, width: float, period: float, tdelay: float = 0.0) -> str:
    """``PT hold,width[,period[,Tdelay]]``: hold time, pulse width and pulse period of the ``PV``/``PI``/``PWV``/
    ``PWI`` pulse source (PG PDF 486-487, printed 4-168 to 4-169).

    ``hold`` 0-655.35 s (10 ms steps); ``width`` 10 us-2 s on the 2 us grid (HR/MP/HPSMU: 500 us-2 s, 100 us steps;
    checked per module by R-PULSE-01); ``period`` 5 ms-5 s (0.1 ms steps), at least ``width + 2 ms`` (``width + 10
    ms`` above 100 ms) and always sent, so the preview shows the period that runs (the automatic 0/-1 forms are never
    built; the sweep modes need it anyway); ``tdelay`` (trigger output delay, 0 to width, 0.1 ms steps) is sent only
    when non-zero. Not effective for MM 27/28 (``MCPT``/``MCPNT``).
    """
    hold = _hold(hold, "PT hold")
    width = _width(width, "PT width")
    period = _period(period, width, "PT period")
    tdelay = _finite(tdelay, "PT Tdelay")
    if not 0 <= tdelay <= width or not _on_grid(tdelay, TRIGGER_DELAY_RESOLUTION_S):
        raise ValueError(f"PT Tdelay must be 0 to the width ({width} s) in 0.1 ms steps, got {tdelay}")
    values = [hold, width, period] + ([tdelay] if tdelay else [])
    return "PT " + ",".join(_num(v) for v in values)


def pv(ch: int, vrange: int, base: float, pulse: float, icomp: float) -> str:
    """``PV chnum,vrange,base,pulse,Icomp``: pulsed voltage source (PG PDF 488-489, printed 4-170 to 4-171).

    ``vrange`` from Table 4-4 (PDF 339; the minimum range covering base and pulse, never below a limited-auto code);
    ``base`` and ``pulse`` in V within the module's output (Tables 4-7 ..., ``driver/modules.py``); Icomp is always
    sent and must not be 0 A (its polarity follows the output). Clears, and is cleared by, ``PI``. In MM 5 the pulse
    is synchronized with the ``WV``/``WI`` staircase.
    """
    _choice(vrange, V_RANGE_CODES, "PV vrange")
    base, pulse = _finite(base, "PV base"), _finite(pulse, "PV pulse")
    icomp = _comp(icomp, "PV Icomp")
    return f"PV {_channel(ch)},{vrange},{_num(base)},{_num(pulse)},{_num(icomp)}"


def pi(ch: int, irange: int, base: float, pulse: float, vcomp: float) -> str:
    """``PI chnum,irange,base,pulse,Vcomp``: pulsed current source (PG PDF 485-486, printed 4-167 to 4-168).

    ``irange`` from Table 4-5 (PDF 340); ``base`` and ``pulse`` in A must have the same polarity (zero allowed); Vcomp
    is always sent and must not be 0 V. Clears, and is cleared by, ``PV``.
    """
    _choice(irange, I_OUTPUT_RANGE_CODES, "PI irange")
    base, pulse = _finite(base, "PI base"), _finite(pulse, "PI pulse")
    _same_polarity((base, pulse), "PI base and pulse")
    vcomp = _comp(vcomp, "PI Vcomp")
    return f"PI {_channel(ch)},{irange},{_num(base)},{_num(pulse)},{_num(vcomp)}"


def pwv(ch: int, mode: int, vrange: int, base: float, start: float, stop: float, points: int, icomp: float) -> str:
    """``PWV chnum,mode,range,base,start,stop,step,Icomp``: pulsed voltage sweep source (PG PDF 492-493, printed
    4-174 to 4-175).

    ``mode`` 1 linear single, 2 log single, 3 linear double, 4 log double; ``vrange`` from Table 4-4 (PDF 339);
    ``points`` = the manual's ``step``, 1 to 10001; a log sweep needs ``start``/``stop`` non-zero of one polarity and
    ``base`` not of the other. Icomp is always sent (0 A refused); ``Pcomp`` is not used. Clears ``PWI``, ``WSV`` and
    ``WSI`` (a synchronous source is sent after it).
    """
    mode = _sweep_mode(mode, "PWV")
    _choice(vrange, V_RANGE_CODES, "PWV range")
    base, start, stop = (_finite(v, f"PWV {n}") for v, n in ((base, "base"), (start, "start"), (stop, "stop")))
    _steps(points, "PWV")
    if mode in (2, 4):
        if start == 0 or stop == 0:
            raise ValueError("a log pulsed sweep needs non-zero start and stop (PG PDF 492)")
        _same_polarity((base, start, stop), "PWV base, start and stop of a log sweep")
    icomp = _comp(icomp, "PWV Icomp")
    return f"PWV {_channel(ch)},{mode},{vrange},{_num(base)},{_num(start)},{_num(stop)},{points},{_num(icomp)}"


def pwi(ch: int, mode: int, irange: int, base: float, start: float, stop: float, points: int, vcomp: float) -> str:
    """``PWI chnum,mode,range,base,start,stop,step,Vcomp``: pulsed current sweep source (PG PDF 490-491, printed
    4-172 to 4-173).

    ``mode`` 1-4 as ``PWV``; ``irange`` from Table 4-5 (PDF 340); ``base``, ``start`` and ``stop`` must have the same
    polarity (a log sweep also needs non-zero start and stop); Vcomp is always sent (0 V refused); ``Pcomp`` is not
    used. Clears ``PWV``, ``WSV`` and ``WSI``.
    """
    mode = _sweep_mode(mode, "PWI")
    _choice(irange, I_OUTPUT_RANGE_CODES, "PWI range")
    base, start, stop = (_finite(v, f"PWI {n}") for v, n in ((base, "base"), (start, "start"), (stop, "stop")))
    _steps(points, "PWI")
    _same_polarity((base, start, stop), "PWI base, start and stop")
    if mode in (2, 4) and (start == 0 or stop == 0):
        raise ValueError("a log pulsed sweep needs non-zero start and stop (PG PDF 491)")
    vcomp = _comp(vcomp, "PWI Vcomp")
    return f"PWI {_channel(ch)},{mode},{irange},{_num(base)},{_num(start)},{_num(stop)},{points},{_num(vcomp)}"


def mcpt(hold: float, period: float, mdelay: float = 0.0, average: int = 1, *, t0: float = 0.0) -> str:
    """``MCPT hold[,period[,Mdelay[,average]]]``: hold time, pulse period, measurement timing and averaging of the
    multi-channel pulsed spot/sweep (MM 27/28; PG PDF 464-465, printed 4-146 to 4-147).

    ``hold`` 0-655.35 s (10 ms steps); ``period`` 5 ms-5 s (0.1 ms steps), at least ``t0 + 2 ms`` (``t0 + 10 ms``
    above 100 ms) where ``t0`` = the longest ``MCPNT`` delay + width (pass it as ``t0`` so the rule is checked here);
    always sent (the automatic 0/-1 forms are never built); ``mdelay`` 0 (automatic: the measurement ends when the
    first pulse returns to base) or 2 us to the period (2 us steps; the instrument also needs it below ``period - N -
    2 ms`` for the ADC time N); ``average`` 1-1023 measurements per datum. Optional values are sent only up to the
    last non-default one.
    """
    hold = _hold(hold, "MCPT hold")
    t0 = _finite(t0, "MCPT t0")
    period = _period(period, t0, "MCPT period")
    mdelay = _finite(mdelay, "MCPT Mdelay")
    if mdelay != 0 and (not MCPT_MEASURE_DELAY_GRID_S <= mdelay < period
                        or not _on_grid(mdelay, MCPT_MEASURE_DELAY_GRID_S)):
        raise ValueError(f"MCPT Mdelay must be 0 (automatic) or 2 us to the period on the 2 us grid, got {mdelay}")
    if not 1 <= _int(average, "MCPT average") <= MCPT_MAX_AVERAGE:
        raise ValueError(f"MCPT average must be 1 to {MCPT_MAX_AVERAGE}, got {average}")
    values: list[float] = [hold, period]
    if mdelay or average != 1:
        values.append(mdelay)
    if average != 1:
        values.append(average)
    return "MCPT " + ",".join(_num(v) for v in values)


def mcpnt(ch: int, delay: float, width: float) -> str:
    """``MCPNT chnum,delay,width``: delay (from the start of the period to the leading edge) and width of one pulse
    channel in MM 27/28 (PG PDF 461-462, printed 4-143 to 4-144; Table 4-27).

    ``delay`` >= 0 on the 2 us grid (HR/MP/HPSMU: 0 only; delay + width within the ``MCPT`` period); ``width`` 10 us-2
    s on the 2 us grid (HR/MP/HPSMU: 500 us-2 s in 100 us steps, the same width on every channel; R-PULSE-01).
    """
    delay = _finite(delay, "MCPNT delay")
    if delay < 0 or delay > PULSE_MAX_PERIOD_S or not _on_grid(delay, PULSE_WIDTH_GRID_S):
        raise ValueError(f"MCPNT delay must be 0 to {PULSE_MAX_PERIOD_S} s on the 2 us grid, got {delay}")
    width = _width(width, "MCPNT width")
    return f"MCPNT {_channel(ch)},{_num(delay)},{_num(width)}"


def mcpnx(n: int, ch: int, source: str, rng: int, base: float, pulse: float, comp: float) -> str:
    """``MCPNX N,chnum,mode,range,base,pulse,comp``: pulsed bias source ``N`` of MM 27/28 (PG PDF 462-463, printed
    4-144 to 4-145).

    ``source`` ``"V"`` (mode 1, ``rng`` from Table 4-4, ``comp`` = Icomp in A) or ``"I"`` (mode 2, ``rng`` from
    Table 4-5, ``comp`` = Vcomp in V; base and pulse of the same polarity); ``comp`` is always sent and must not be 0.
    ``N`` (1-10) and the channel are unique over ``MCPNX``, ``MCPWNX`` and ``WNX``.
    """
    _source_number(n, "MCPNX")
    mode = _source(source, "MCPNX")
    _choice(rng, V_RANGE_CODES if source == "V" else I_OUTPUT_RANGE_CODES, f"MCPNX range ({source} source)")
    base, pulse = _finite(base, "MCPNX base"), _finite(pulse, "MCPNX pulse")
    if source == "I":
        _same_polarity((base, pulse), "MCPNX base and pulse of a current source")
    comp = _comp(comp, "MCPNX comp")
    return f"MCPNX {n},{_channel(ch)},{mode},{rng},{_num(base)},{_num(pulse)},{_num(comp)}"


def mcpws(mode: int, points: int) -> str:
    """``MCPWS mode,step``: sweep mode (1 linear single, 2 log single, 3 linear double, 4 log double) and number of
    sweep steps (1-10001) of every sweep source of MM 28 (PG PDF 465, printed 4-147)."""
    return f"MCPWS {_sweep_mode(mode, 'MCPWS')},{_steps(points, 'MCPWS')}"


def mcpwnx(n: int, ch: int, source: str, rng: int, base: float, start: float, stop: float, comp: float) -> str:
    """``MCPWNX N,chnum,mode,range,base,start,stop,comp``: pulsed sweep source ``N`` of MM 28 (PG PDF 465-467,
    printed 4-147 to 4-149).

    ``source`` ``"V"`` (mode 1; Table 4-4 range; ``comp`` = Icomp) or ``"I"`` (mode 2; Table 4-5 range; ``comp`` =
    Vcomp; base, start and stop of the same polarity); start = stop makes it a pulsed bias; sweep mode and steps are
    ``MCPWS``'s (a log sweep needs non-zero start/stop of one polarity: checked by the setup, which knows the mode).
    ``comp`` is always sent and must not be 0; ``Pcomp`` is not used.
    """
    _source_number(n, "MCPWNX")
    mode = _source(source, "MCPWNX")
    _choice(rng, V_RANGE_CODES if source == "V" else I_OUTPUT_RANGE_CODES, f"MCPWNX range ({source} source)")
    base, start, stop = (_finite(v, f"MCPWNX {k}") for v, k in ((base, "base"), (start, "start"), (stop, "stop")))
    if source == "I":
        _same_polarity((base, start, stop), "MCPWNX base, start and stop of a current source")
    comp = _comp(comp, "MCPWNX comp")
    return f"MCPWNX {n},{_channel(ch)},{mode},{rng},{_num(base)},{_num(start)},{_num(stop)},{_num(comp)}"
