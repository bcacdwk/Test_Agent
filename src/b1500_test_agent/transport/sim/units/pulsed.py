"""SMU pulsed unit of the simulator (``MM 3``, ``4``, ``5``, ``27``, ``28``): ``PT``, ``PV``, ``PI``, ``PWV``, ``PWI``,
``MCPT``, ``MCPNT``, ``MCPNX``, ``MCPWS``, ``MCPWNX`` and the pulsed measurement engine (blueprint v2 4.1, kind
``smu_pulsed``, WP7.3).

``PulsedUnit`` is a mixin of ``SimInstrument``. ``SmuUnit._cmd_mm`` accepts the pulsed modes and ``SmuUnit._cmd_xe``
hands their triggers to ``_start_pulsed``; the synchronous ``WSV``/``WSI`` source of MM 4 follows the pulsed sweep and
the ``WNX`` sources of MM 28 follow ``MCPWS`` (``_pulsed_follow_mode``). Manual references (Programming Guide Ed. 15,
physical PDF pages): operation MM 3 p93, MM 27 p94-95, MM 5 p98-99, MM 4 p100-101, MM 28 p104-105; ``PT`` 486-487;
``PV`` 488-489; ``PI`` 485-486; ``PWV`` 492-493; ``PWI`` 490-491; ``MCPT`` 464-465; ``MCPNT`` 461-462 (Table 4-27);
``MCPNX`` 462-463; ``MCPWS`` 465; ``MCPWNX`` 465-467; errors 221-233, 238, 239 (PDF 579-580).

Engine (everything is evaluated at ``XE`` in virtual time, like the staircase):

- Timing: after the hold time every step is one pulse period: the staircase sources (MM 5 ``WV``/``WI`` and its
  synchronous source, MM 28 ``WNX``) take the step's value for the whole period, each pulse source is at its peak
  from its delay (``MCPNT``; 0 for ``PT``) for its width and at its base otherwise. The measurement window is the
  pulsed ADC's time (``AIT 2,3,N``; another ``AIT 2`` mode counts its PLC time) ending with the first pulse that ends
  (MM 27/28 ``Mdelay`` 0, MM 3/4/5 the pulse end) or starting at ``Mdelay``; it is shortened to the pulse width when
  longer. ``MCPT`` average repeats every step that many times (one pulse each) and averages the readings.
- Physics: the dynamic devices evolve through every segment of every period (``Circuit.advance`` under the applied
  voltages: self-heating relaxes with ``tau_th``, FeFET kinetics, ...); compliance limits the applied voltages as for
  a DC level (``SmuUnit.solve``). A reading is the mean of the channel's current (or voltage) at the start and the end
  of the measurement window; a voltage source whose transient current exceeds its compliance reads the compliance
  value with status ``C`` (``T`` on the other channels). Noise as the DC measurements, with the multiplier of the
  pulsed ADC's time (3x below 0.25 PLC). In pulsed measurements a current channel measures on a fixed range: the
  compliance range for ranging code 0 (PG Table 4-3 footnote "using pulse", PDF 337), else the given range.
- ``WM 2`` (MM 4, 5, 28): compliance (``C``/``T``), overflow (``V``) or oscillation (``X``) aborts: later steps are
  ``199.999E+99`` with status ``V``. After the measurement every pulse source holds its base value, the staircase and
  synchronous sources their start value (or stop with ``WM`` post 2 after a normal end, PDF 99, 101, 105).
- Data per step (FMT 1/5): ``[Time,]Data`` per measured channel in ``MM`` order, then with FMT mode 1 (MM 4, 5) the
  primary sweep source's value, with mode N (MM 28) that of source ``N`` (status ``W``, ``E`` on the last step).
- Errors: 221 (MM 4 without ``PWV``/``PWI``; ``WSV``/``WSI`` without any primary sweep: 220), 222 (MM 5 without
  ``PV``/``PI``), 230 (MM 3 without them),
  220 (MM 5 without ``WV``/``WI``), 226 (log sweep in MM 4/5), 224 (synchronous source in another output mode or on the
  primary channel), 231 (pulse compliance), 232 (MM 27/28 without a usable source, a staircase source on a pulse
  channel), 233 (period shorter than delay + width + 2 ms / 10 ms; an HR/MP/HPSMU pulse narrower than 500 us or with
  a delay: simulator convention, TODO(verify) at L5), 238/239 (width above 2 s / below 10 us).

Simulator conventions (TODO(verify) at bring-up stage L5): no edge settling or overshoot; the readings carry no
displacement current of the pulse edges; stateful devices without dynamics (attached noise) keep their state during
a pulsed measurement.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import DUMMY_VALUE, Element, worst_status
from b1500_test_agent.transport.sim.units.base import Measurement, handles
from b1500_test_agent.transport.sim.units.core import NOISE_MULTIPLIERS
from b1500_test_agent.transport.sim.units.smu import OVERRANGE, SweepSource, force_source, max_vcomp

PULSED_MODES = frozenset({3, 4, 5, 27, 28})
"""The SMU pulsed measurement modes (Table 4-28, PDF 471)."""

SINGLE_CHANNEL_MODES = frozenset({3, 4, 5})
"""MM 3, 4, 5 take exactly one measurement channel (MM syntax, PDF 470)."""

SWEEP_MODES = frozenset({4, 5, 28})

PT_INITIAL = (0.0, 1e-3, 1e-2, 0.0)
"""``PT`` initial setting: hold 0 s, width 1 ms, period 10 ms, trigger delay 0 (PDF 486-487)."""

MCPT_INITIAL = (0.0, 1e-2, 0.0, 1)
"""``MCPT`` initial setting: hold 0 s, period 10 ms, Mdelay 0 (automatic), average 1 (PDF 464-465)."""

MCPNT_INITIAL = (0.0, 1e-3)
"""``MCPNT`` initial delay and width of a channel (Table 4-27, PDF 462)."""

HR_MP_TYPES = frozenset({"HRSMU", "MPSMU", "HPSMU"})
HR_MP_MIN_WIDTH_S = 5e-4
"""HR/MP/HPSMU pulse widths start at 500 us (PT PDF 486, Table 4-27 PDF 462)."""

MAX_SMU_CURRENT_A = 0.1


@dataclass(frozen=True)
class PulseOut:
    """One pulse source: ``PV``/``PI`` (``start`` = ``stop`` = the peak), ``PWV``/``PWI`` or ``MCPNX``/``MCPWNX``.

    ``source`` is what it forces (``V``/``I``), ``comp`` the compliance magnitude (A for V, V for I)."""

    channel: int
    source: str
    out_range: int
    base: float
    start: float
    stop: float
    comp: float
    mode: int = 1
    steps: int = 1
    sweeping: bool = False

    def peaks(self, mode: int, steps: int) -> list[float]:
        """The peak value of every step (a pulsed bias repeats its peak)."""
        if not self.sweeping:
            return [self.start] * (steps * (2 if mode in (3, 4) else 1))
        return SweepSource(self.channel, self.source, self.start, self.stop, self.comp).values(mode, steps)


@dataclass
class PulsePlan:
    """A pulsed measurement ready to evaluate (built by ``_pulsed_plan``)."""

    mode: int
    hold: float
    period: float
    average: int
    window: tuple[float, float]
    """Measurement window (start, end) within each period."""
    pulses: list[tuple[PulseOut, float, float, list[float]]]
    """``(source, delay, width, peak per step)``."""
    stairs: list[tuple[SweepSource, list[float]]] = field(default_factory=list)
    """Staircase sources with their value per step (MM 5 primary + synchronous, MM 4 synchronous, MM 28 ``WNX``)."""
    returned: tuple[int, str, list[float]] | None = None
    """``(channel, V|I, value per step)`` of the source whose value each step returns."""
    steps: int = 1


class PulsedUnit:
    """Pulsed handlers and engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_pulsed_settings(self) -> None:
        """Pulse setup to its initial settings (PG Table 2-13, PDF 180)."""
        self._pt: tuple[float, float, float, float] = PT_INITIAL
        self._pulse_bias: PulseOut | None = None
        self._pulse_sweep: PulseOut | None = None
        self._mcpt: tuple[float, float, float, int] = MCPT_INITIAL
        self._mcpnt: dict[int, tuple[float, float]] = {}
        self._mcp: dict[int, PulseOut] = {}
        self._mcpws: tuple[int, int] = (1, 1)

    # -- timing --------------------------------------------------------------------------------------------------------

    @staticmethod
    def _pulse_width(arg: str) -> float:
        width = flex.number(arg)
        if width > 2.0:
            raise flex.FlexError(flex.ERR_PULSE_WIDTH_MAX, f"width {width}")
        if width < 1e-5:
            raise flex.FlexError(flex.ERR_PULSE_WIDTH_MIN, f"width {width}")
        return width

    @staticmethod
    def _pulse_period(arg: str) -> float:
        period = flex.number(arg)
        if period in (0.0, -1.0):
            raise flex.FlexError(flex.ERR_PULSE_TIMING, "automatic pulse periods (0, -1) are not simulated")
        if not 5e-3 <= period <= 5.0:
            raise flex.FlexError(flex.ERR_PULSE_TIMING, f"period {period}")
        return period

    @staticmethod
    def _pulse_hold(arg: str) -> float:
        hold = flex.number(arg)
        if not 0 <= hold <= 655.35:
            raise flex.FlexError(flex.ERR_PARAMETER, f"hold {hold}")
        return hold

    @handles("PT")
    def _cmd_pt(self, cmd: flex.Command) -> None:
        """``PT hold,width[,period[,Tdelay]]`` (PDF 486-487); the period/width rule is checked at ``XE``."""
        flex.arity(cmd, 2, 4)
        hold, width = self._pulse_hold(cmd.args[0]), self._pulse_width(cmd.args[1])
        period = self._pulse_period(cmd.args[2]) if len(cmd.args) > 2 else self._pt[2]
        tdelay = flex.number(cmd.args[3]) if len(cmd.args) > 3 else 0.0
        if not 0 <= tdelay <= width:
            raise flex.FlexError(flex.ERR_PARAMETER, f"Tdelay {tdelay}")
        self._pt = (hold, width, period, tdelay)

    @handles("MCPT")
    def _cmd_mcpt(self, cmd: flex.Command) -> None:
        """``MCPT hold[,period[,Mdelay[,average]]]`` (PDF 464-465)."""
        flex.arity(cmd, 1, 4)
        hold = self._pulse_hold(cmd.args[0])
        period = self._pulse_period(cmd.args[1]) if len(cmd.args) > 1 else MCPT_INITIAL[1]
        mdelay = flex.number(cmd.args[2]) if len(cmd.args) > 2 else 0.0
        average = flex.integer(cmd.args[3]) if len(cmd.args) > 3 else 1
        if mdelay < 0 or mdelay >= period or not 1 <= average <= 1023:
            raise flex.FlexError(flex.ERR_PARAMETER, f"Mdelay {mdelay} average {average}")
        self._mcpt = (hold, period, mdelay, average)

    @handles("MCPNT")
    def _cmd_mcpnt(self, cmd: flex.Command) -> None:
        """``MCPNT chnum,delay,width`` (PDF 461-462)."""
        flex.arity(cmd, 3, 3)
        channel = self._smu(cmd.args[0])
        delay = flex.number(cmd.args[1])
        if delay < 0 or delay > 5.0:
            raise flex.FlexError(flex.ERR_PARAMETER, f"delay {delay}")
        self._mcpnt[channel] = (delay, self._pulse_width(cmd.args[2]))

    # -- sources -------------------------------------------------------------------------------------------------------

    def _pulse_levels(self, channel: int, source: str, range_arg: str, levels: list[str],
                      comp_arg: str | None) -> tuple[int, list[float], float]:
        """Range, levels and compliance of a pulse source: within the module's output (100 V or 100 mA), a current
        source of one polarity, an explicit non-zero compliance within the module (error 231), the interlock."""
        if source == "V":
            rng = flex.integer(range_arg)
            if rng not in flex.V_RANGE_MAX:
                raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        else:
            rng = self._output_irange(channel, range_arg)
        values = [flex.number(v) for v in levels]
        peak = max(abs(v) for v in values)
        if peak > (flex.SMU_MAX_V if source == "V" else MAX_SMU_CURRENT_A):
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} {source}")
        if source == "I" and any(v > 0 for v in values) and any(v < 0 for v in values):
            raise flex.FlexError(flex.ERR_PARAMETER, "current pulse levels of both polarities")
        if comp_arg is None:
            raise flex.FlexError(flex.ERR_PULSE_COMPLIANCE, "the compliance is always sent by this driver")
        comp = abs(flex.number(comp_arg))
        allowed = flex.max_icomp(peak) if source == "V" else max_vcomp(peak)
        if comp == 0 or comp > allowed:
            raise flex.FlexError(flex.ERR_PULSE_COMPLIANCE, f"comp {comp}")
        self._check_interlock(peak if source == "V" else comp)
        return rng, values, comp

    @handles("PV", "PI")
    def _cmd_pulse_bias(self, cmd: flex.Command) -> None:
        """``PV chnum,vrange,base,pulse[,Icomp]`` / ``PI chnum,irange,base,pulse[,Vcomp]`` (PDF 485-489); each clears
        the other."""
        flex.arity(cmd, 4, 5)
        source = "V" if cmd.mnemonic == "PV" else "I"
        channel = self._smu(cmd.args[0])
        rng, (base, peak), comp = self._pulse_levels(channel, source, cmd.args[1], list(cmd.args[2:4]),
                                                     cmd.args[4] if len(cmd.args) > 4 else None)
        self._pulse_bias = PulseOut(channel, source, rng, base, peak, peak, comp)

    @handles("PWV", "PWI")
    def _cmd_pulse_sweep(self, cmd: flex.Command) -> None:
        """``PWV chnum,mode,range,base,start,stop,step[,Icomp[,Pcomp]]`` / ``PWI ...`` (PDF 490-493); clears the other
        pulsed sweep and the synchronous ``WSV``/``WSI`` source. ``Pcomp`` is not simulated (error 100)."""
        flex.arity(cmd, 7, 8)
        source = "V" if cmd.mnemonic == "PWV" else "I"
        channel = self._smu(cmd.args[0])
        mode = self._sweep_mode(cmd.args[1])
        rng, (base, start, stop), comp = self._pulse_levels(channel, source, cmd.args[2], list(cmd.args[3:6]),
                                                            cmd.args[7] if len(cmd.args) > 7 else None)
        if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0) or base * start < 0):
            raise flex.FlexError(flex.ERR_LOG_POLARITY)
        steps = self._steps(cmd.args[6])
        self._pulse_sweep = PulseOut(channel, source, rng, base, start, stop, comp, mode, steps, sweeping=True)
        self._sync = None

    def _mcp_claim(self, n: int, channel: int) -> None:
        """Source number ``n`` and ``channel`` replace earlier ``MCPNX``/``MCPWNX``/``WNX`` settings (PDF 463, 467)."""
        self._mcp = {k: v for k, v in self._mcp.items() if k != n and v.channel != channel}
        self._wnx = {k: v for k, v in self._wnx.items() if k != n and v.channel != channel}

    def _mcp_forget(self, n: int, channel: int) -> None:
        """A ``WNX`` setting replaces the ``MCPNX``/``MCPWNX`` source with the same number or channel."""
        self._mcp = {k: v for k, v in self._mcp.items() if k != n and v.channel != channel}

    @handles("MCPNX", "MCPWNX")
    def _cmd_mcp_source(self, cmd: flex.Command) -> None:
        """``MCPNX N,chnum,mode,range,base,pulse[,comp]`` / ``MCPWNX N,chnum,mode,range,base,start,stop[,comp[,Pcomp]]``
        (PDF 462-467): pulsed bias / pulsed sweep source ``N`` of MM 27/28."""
        sweep = cmd.mnemonic == "MCPWNX"
        flex.arity(cmd, 6 if not sweep else 7, 7 if not sweep else 8)
        n = flex.integer(cmd.args[0])
        if not 1 <= n <= 10:
            raise flex.FlexError(flex.ERR_PARAMETER, f"N {n}")
        channel = self._smu(cmd.args[1])
        kind = flex.integer(cmd.args[2])
        if kind not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {kind}")
        source = "V" if kind == 1 else "I"
        count = 3 if sweep else 2
        comp_index = 4 + count
        rng, values, comp = self._pulse_levels(channel, source, cmd.args[3], list(cmd.args[4:4 + count]),
                                               cmd.args[comp_index] if len(cmd.args) > comp_index else None)
        base, start, stop = (values[0], values[1], values[1]) if not sweep else tuple(values)
        self._mcp_claim(n, channel)
        self._mcp[n] = PulseOut(channel, source, rng, base, start, stop, comp, sweeping=sweep)

    @handles("MCPWS")
    def _cmd_mcpws(self, cmd: flex.Command) -> None:
        """``MCPWS mode,step``: sweep mode and steps of MM 28 (PDF 465)."""
        flex.arity(cmd, 2, 2)
        self._mcpws = (self._sweep_mode(cmd.args[0]), self._steps(cmd.args[1]))

    def _pulsed_follow_mode(self, mnemonic: str) -> int | None:
        """Sweep mode a ``WSV``/``WSI`` (the ``PWV``/``PWI`` pulsed sweep's, MM 4; error 220 without any primary) or
        ``WNX`` (``MCPWS``'s, MM 28) source follows when no ``WV``/``WI`` primary is set."""
        if mnemonic == "WNX":
            return self._mcpws[0]
        if self._pulse_sweep is None:
            raise flex.FlexError(flex.ERR_NO_SWEEP, f"{mnemonic} without WV/WI or PWV/PWI")
        return self._pulse_sweep.mode

    # -- trigger -------------------------------------------------------------------------------------------------------

    def _pulse_timing_ok(self, channel: int, delay: float, width: float, period: float) -> None:
        """Error 233 for a period shorter than delay + width + 2 ms (10 ms above 100 ms) or an HR/MP/HPSMU pulse
        narrower than 500 us or delayed (PDF 462, 487)."""
        t0 = delay + width
        margin = 2e-3 if t0 <= 0.1 else 1e-2
        if period < t0 + margin - 1e-12:
            raise flex.FlexError(flex.ERR_PULSE_TIMING, f"period {period} < {t0} + {margin}")
        if self._channel_type(channel) in HR_MP_TYPES and (width < HR_MP_MIN_WIDTH_S - 1e-12 or delay != 0):
            raise flex.FlexError(flex.ERR_PULSE_TIMING, f"width {width} / delay {delay} on an HR/MP/HPSMU")

    def _measure_time(self) -> float:
        """Time of one pulsed measurement: the pulsed ADC's ``AIT 2`` setting (mode 3 seconds, mode 2 PLCs)."""
        mode, n = self._ait[2]
        return float(n) if mode == 3 else float(n) / flex.LINE_FREQUENCY_HZ

    def _pulsed_plan(self, mode: int, channels: list[int]) -> PulsePlan:
        """The sources, timing and window of the pulsed measurement ``mode`` (errors: module docstring)."""
        meas = self._measure_time()
        if mode in SINGLE_CHANNEL_MODES:
            hold, width, period, _ = self._pt
            if mode == 4:
                pulse = self._pulse_sweep
                if pulse is None:
                    raise flex.FlexError(flex.ERR_NO_PULSE_SWEEP)
                if pulse.mode in (2, 4):
                    raise flex.FlexError(flex.ERR_PULSE_LINEAR)
                steps, sweep_mode = pulse.steps, pulse.mode
            else:
                pulse = self._pulse_bias
                if pulse is None:
                    raise flex.FlexError(flex.ERR_NO_PULSE_BIAS if mode == 5 else flex.ERR_NO_PULSE_SOURCE)
                steps, sweep_mode = 1, 1
            stairs: list[tuple[SweepSource, list[float]]] = []
            returned = None
            if mode == 5:
                if self._sweep is None:
                    raise flex.FlexError(flex.ERR_NO_SWEEP)
                if self._sweep.mode in (2, 4):
                    raise flex.FlexError(flex.ERR_PULSE_LINEAR)
                steps, sweep_mode = self._sweep.steps, self._sweep.mode
                primary = self._sweep.primary
                stairs.append((primary, primary.values(sweep_mode, steps)))
                returned = (primary.channel, primary.source, stairs[0][1])
                if primary.channel == pulse.channel:
                    raise flex.FlexError(flex.ERR_PULSE_SETUP, "pulse source on the staircase channel")
            if mode in (4, 5) and self._sync is not None:
                lead = self._sweep.primary if mode == 5 and self._sweep is not None else pulse
                if self._sync.source != lead.source or self._sync.channel in (lead.channel, pulse.channel):
                    raise flex.FlexError(flex.ERR_SYNC_MODE)
                stairs.append((self._sync, self._sync.values(sweep_mode, steps)))
            self._pulse_timing_ok(pulse.channel, 0.0, width, period)
            peaks = pulse.peaks(sweep_mode, steps)
            if mode == 4:
                returned = (pulse.channel, pulse.source, peaks)
            end = width
            window = (max(0.0, end - meas), end)
            total = len(peaks)
            return PulsePlan(mode, hold, period, 1, window, [(pulse, 0.0, width, peaks)], stairs, returned, total)
        hold, period, mdelay, average = self._mcpt
        if mode == 27:
            sources = {n: s for n, s in self._mcp.items() if not s.sweeping}
            steps, sweep_mode = 1, 1
            wnx: dict[int, SweepSource] = {}
        else:
            sources = dict(self._mcp)
            sweep_mode, steps = self._mcpws
            wnx = dict(self._wnx)
            if not any(s.sweeping for s in sources.values()) and not wnx:
                raise flex.FlexError(flex.ERR_PULSE_SETUP, "MM 28 without MCPWNX or WNX sweep source")
        if not sources:
            raise flex.FlexError(flex.ERR_PULSE_SETUP, f"MM {mode} without MCPNX/MCPWNX pulse source")
        pulse_channels = {s.channel for s in sources.values()}
        if any(item.channel in pulse_channels for item in wnx.values()):
            raise flex.FlexError(flex.ERR_PULSE_SETUP, "WNX source on a pulse channel")
        if sweep_mode in (2, 4):
            for item in [*(s for s in sources.values() if s.sweeping), *wnx.values()]:
                if item.start == 0 or item.stop == 0 or (item.start > 0) != (item.stop > 0):
                    raise flex.FlexError(flex.ERR_LOG_POLARITY)
        pulses: list[tuple[PulseOut, float, float, list[float]]] = []
        for _, source in sorted(sources.items()):
            delay, width = self._mcpnt.get(source.channel, MCPNT_INITIAL)
            self._pulse_timing_ok(source.channel, delay, width, period)
            pulses.append((source, delay, width, source.peaks(sweep_mode, steps)))
        first_end = min(delay + width for _, delay, width, _ in pulses)
        if mdelay > 0:
            window = (mdelay, min(mdelay + meas, period))
        else:
            window = (max(0.0, first_end - meas), first_end)
        stairs = [(item, item.values(sweep_mode, steps)) for _, item in sorted(wnx.items())]
        total = steps * (2 if sweep_mode in (3, 4) else 1)
        returned = None
        n_returned = self._fmt_mode
        if mode == 28 and n_returned:
            if n_returned in sources:
                src = sources[n_returned]
                returned = (src.channel, src.source, src.peaks(sweep_mode, steps))
            elif n_returned in wnx:
                item = wnx[n_returned]
                returned = (item.channel, item.source, item.values(sweep_mode, steps))
            else:
                raise flex.FlexError(flex.ERR_NO_SYNC_DATA, f"FMT mode {n_returned} names no source")
        return PulsePlan(mode, hold, period, average, window, pulses, stairs, returned, total)

    def _start_pulsed(self, mode: int, channels: list[int]) -> None:
        """``XE`` with a pulsed ``MM``: check the setup, evaluate the measurement, busy until its end."""
        plan = self._pulsed_plan(mode, channels)
        involved = [*channels, *(p.channel for p, *_ in plan.pulses), *(s.channel for s, _ in plan.stairs)]
        for channel in involved:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        self._measurement = self._measure_pulsed(plan, channels, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    # -- engine --------------------------------------------------------------------------------------------------------

    def _pulse_levels_at(self, plan: PulsePlan, step: int, t: float, levels0: dict[int, float],
                         currents0: dict[int, tuple[float, float]]) -> tuple[dict[int, float],
                                                                             dict[int, tuple[float, float]]]:
        """Voltage levels and current sources ``{channel: (current, Vcomp)}`` at time ``t`` of step ``step``'s
        period."""
        levels = dict(levels0)
        currents = dict(currents0)
        for stair, values in plan.stairs:
            if stair.source == "V":
                levels[stair.channel] = values[step]
                currents.pop(stair.channel, None)
            else:
                currents[stair.channel] = (values[step], stair.comp)
                levels.pop(stair.channel, None)
        for pulse, delay, width, peaks in plan.pulses:
            value = peaks[step] if delay - 1e-15 <= t < delay + width - 1e-15 else pulse.base
            if pulse.source == "V":
                levels[pulse.channel] = value
                currents.pop(pulse.channel, None)
            else:
                currents[pulse.channel] = (value, pulse.comp)
                levels.pop(pulse.channel, None)
        return levels, currents

    def _pulse_icomps(self, plan: PulsePlan, levels: dict[int, float]) -> dict[int, float]:
        comps = {ch: self._icomp(ch) for ch in levels}
        for stair, _ in plan.stairs:
            if stair.source == "V":
                comps[stair.channel] = stair.comp
        for pulse, *_ in plan.pulses:
            if pulse.source == "V":
                comps[pulse.channel] = pulse.comp
        return {ch: comps[ch] for ch in levels}

    def _hold_segment(self, plan: PulsePlan, step: int, start: float, end: float, levels0: dict[int, float],
                      currents0: dict[int, tuple[float, float]]) -> tuple[dict[int, float], dict[int, float], set[int]]:
        """Apply the outputs of ``[start, end)`` of a period (solved with compliance) and let the dynamic devices
        evolve over it; returns the applied voltages, the currents at its end and the channels in compliance."""
        levels, currents = self._pulse_levels_at(plan, step, start, levels0, currents0)
        applied, measured, clamped = self.solve(levels, self._pulse_icomps(plan, levels), currents)
        if self.circuit.dynamic:  # also for a zero-length segment: the currents at the present device state
            evolved = self.circuit.advance(max(end - start, 0.0), applied)
            measured = {ch: float(evolved.get(ch, measured.get(ch, 0.0))) for ch in measured}
        return applied, measured, clamped

    def _period_edges(self, plan: PulsePlan) -> list[float]:
        edges = {0.0, plan.period, *plan.window}
        for _, delay, width, _ in plan.pulses:
            edges.update((delay, delay + width))
        return sorted(e for e in edges if 0.0 <= e <= plan.period)

    def _pulse_reading(self, plan: PulsePlan, step: int, levels0: dict[int, float],
                       currents0: dict[int, tuple[float, float]]) -> tuple[dict[int, float], dict[int, float],
                                                                           set[int]]:
        """One period of step ``step``: the devices evolve segment by segment (edges of every pulse and of the
        measurement window); returns the applied voltages at the window end, the mean of every channel's current at
        the window start and end, and the channels in compliance inside the window."""
        edges = self._period_edges(plan)
        w_start, w_end = plan.window
        at_start: dict[int, float] | None = None
        at_end: dict[int, float] = {}
        applied_end: dict[int, float] = {}
        clamped_window: set[int] = set()
        if w_start <= 0.0:
            _, at_start, _ = self._hold_segment(plan, step, 0.0, 0.0, levels0, currents0)
        for left, right in itertools.pairwise(edges):
            applied, currents, clamped = self._hold_segment(plan, step, left, right, levels0, currents0)
            if left >= w_start - 1e-15 and right <= w_end + 1e-15:
                clamped_window |= clamped
            if at_start is None and math.isclose(right, w_start, rel_tol=0.0, abs_tol=1e-15):
                at_start = currents
            if math.isclose(right, w_end, rel_tol=0.0, abs_tol=1e-15):
                at_end, applied_end = currents, applied
        start_values = at_start if at_start is not None else at_end
        mean = {ch: 0.5 * (start_values.get(ch, 0.0) + value) for ch, value in at_end.items()}
        return applied_end, mean, clamped_window

    def _pulse_noise(self, channel: int, current: float, multiplier: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = multiplier * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0

    def _measure_pulsed(self, plan: PulsePlan, channels: list[int], t0: float) -> Measurement:
        factor = self.faults.slow_factor()
        meas = plan.window[1] - plan.window[0]
        multiplier = next(m for limit, m in NOISE_MULTIPLIERS if meas * flex.LINE_FREQUENCY_HZ < limit)
        levels0 = dict(self._on_levels())
        currents0 = dict(self._on_currents())
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        if plan.hold > 0 and self.circuit.dynamic:  # hold: staircases at their first value, pulses at base
            levels, currents = self._pulse_levels_at(plan, 0, -1.0, levels0, currents0)
            applied, _, _ = self.solve(levels, self._pulse_icomps(plan, levels), currents)
            self.circuit.advance(plan.hold, applied)
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        aborted = False
        zero_at: float | None = None
        last = plan.steps - 1
        abort_on = plan.mode in SWEEP_MODES and self._wm[0] == 2
        for step in range(plan.steps):
            start = plan.hold + step * plan.period * plan.average
            end = t0 + factor * (start + plan.period * plan.average)
            stamp = t0 + factor * (start + plan.window[0]) - self._timer_zero
            step_ends.append(end)
            if aborted:
                blocks.append(self._pulse_dummy(plan, channels, step, stamp, last))
                continue
            if self.faults.interlock_opens_at(step):
                self._interlock_open = True
            levels, currents = self._pulse_levels_at(plan, step, plan.window[0], levels0, currents0)
            potentials = {**levels, **{ch: vcomp for ch, (_, vcomp) in currents.items()}}
            if self.interlock_open() and self._high_voltage(potentials):
                self._queue_error(flex.ERR_INTERLOCK)  # all outputs to 0 V, error 202 (PG PDF 577)
                zero_at = end
                aborted = True
                blocks.append(self._pulse_dummy(plan, channels, step, stamp, last))
                continue
            readings = [self._pulse_reading(plan, step, levels0, currents0) for _ in range(plan.average)]
            applied = readings[-1][0]
            mean = {ch: sum(r[1].get(ch, 0.0) for r in readings) / plan.average for ch in readings[-1][1]}
            clamped = set().union(*(r[2] for r in readings))
            texts, statuses = self._pulse_texts(plan, channels, step, stamp, last, applied, mean, clamped,
                                                currents, multiplier, rng)
            blocks.append(texts)
            if self.circuit.has_state:
                device_states.append(self.circuit.export_state())
            if abort_on and any(s in "CTVX" for s in statuses):
                aborted = True
        self._sync_devices()
        post_stop = self._wm[1] == 2
        on_end = self._pulse_end_action(plan, post_stop)
        measurement = Measurement(t0, step_ends[-1], step_ends, blocks, None, None, zero_at, device_states)
        measurement.on_end = on_end
        return measurement

    def _pulse_end_action(self, plan: PulsePlan, post_stop: bool) -> Callable[[bool], None]:
        """After the measurement every pulse source holds its base value; the staircase and synchronous sources their
        start value, or their stop value with ``WM`` post 2 after a normal end (PDF 99, 101, 105)."""
        pulses = [(p.channel, p.source, p.base, p.comp) for p, *_ in plan.pulses]
        stairs = [(s.channel, s.source, s.start, s.stop, s.comp) for s, _ in plan.stairs]

        def apply(aborted: bool) -> None:
            for channel, source, base, comp in pulses:
                state = self.state.channels[channel]
                if state.output_on:
                    force_source(state, source, base, comp)  # type: ignore[arg-type]
            for channel, source, start, stop, comp in stairs:
                state = self.state.channels[channel]
                if state.output_on:
                    force_source(state, source, stop if post_stop and not aborted else start, comp)  # type: ignore[arg-type]

        return apply

    def _pulse_quantity(self, channel: int, currents: dict[int, tuple[float, float]]) -> str:
        mode = self._cmm.get(channel, 0)
        forces_current = channel in currents
        if mode == 1:
            return "I"
        if mode == 2:
            return "V"
        if mode == 3:
            return "I" if forces_current else "V"
        return "V" if forces_current else "I"

    def _pulse_texts(self, plan: PulsePlan, channels: list[int], step: int, stamp: float, last: int,
                     applied: dict[int, float], mean: dict[int, float], clamped: set[int],
                     currents: dict[int, tuple[float, float]], multiplier: float,
                     rng: random.Random) -> tuple[list[str], list[str]]:
        comps = self._pulse_icomps(plan, {ch: 0.0 for ch in applied if ch not in currents})
        over = {ch for ch, value in mean.items() if ch in comps and abs(value) > comps[ch] * (1 + 1e-9)}
        faulted = {canonical_channel(ch) for ch in self.faults.compliance_channels(step)}
        limited = clamped | over | faulted
        oscillating = self.faults.oscillating(step)
        texts: list[str] = []
        statuses: list[str] = []
        offset = 0.0
        for channel in channels:
            quantity = self._pulse_quantity(channel, currents)
            status = "C" if channel in limited else ("T" if limited else "N")
            if quantity == "I":
                reading = mean.get(channel, 0.0)
                if channel in comps and (channel in over or channel in faulted):
                    sign = reading if reading != 0 else (applied.get(channel, 0.0) or 1.0)
                    reading = math.copysign(comps[channel], sign)
                else:
                    reading += self._pulse_noise(channel, reading, multiplier, rng)
                code = self._ri.get(channel, 0)
                full_scale = flex.current_range(code) if code != 0 else None
                if full_scale is not None and abs(reading) > OVERRANGE * full_scale:
                    status = worst_status([status, "V"])
            else:
                reading = applied.get(channel, 0.0)
                if channel in faulted and channel in currents:
                    target, vcomp = currents[channel]
                    reading = math.copysign(vcomp, target if target != 0 else 1.0)
            if oscillating:
                status = worst_status([status, "X"])
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp + offset).text())
            texts.append(Element(status, channel, quantity, reading).text())
            statuses.append(status)
        if self.faults.garbage_at(step):
            texts[1 if self._tsc else 0] = GARBAGE_ELEMENT
        texts += self._pulse_source_element(plan, step, last)
        return texts, statuses

    def _pulse_source_element(self, plan: PulsePlan, step: int, last: int) -> list[str]:
        if plan.returned is None or self._fmt_mode == 0 or plan.mode in (3, 27):
            return []
        channel, source, values = plan.returned
        return [Element("E" if step == last else "W", channel, source, values[step]).text()]

    def _pulse_dummy(self, plan: PulsePlan, channels: list[int], step: int, stamp: float, last: int) -> list[str]:
        currents = {p.channel: (0.0, 0.0) for p, *_ in plan.pulses if p.source == "I"}
        texts: list[str] = []
        for channel in channels:
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp).text())
            texts.append(Element("V", channel, self._pulse_quantity(channel, currents), DUMMY_VALUE).text())
        if plan.returned is not None and self._fmt_mode != 0 and plan.mode not in (3, 27):
            channel, source, _ = plan.returned
            texts.append(Element("E" if step == last else "W", channel, source, DUMMY_VALUE).text())
        return texts
