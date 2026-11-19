"""SMU unit of the simulator: ranging, measurement modes, DC and staircase sources, the measurement engine.

``SmuUnit`` is a mixin of ``SimInstrument`` (``transport/sim/instrument.py``): its ``@handles`` methods are the SMU
FLEX handlers of the v1 subset, registered by mnemonic, and ``XE`` evaluates spot (``MM 1``) and staircase sweep
(``MM 2``) measurements on the scenario circuit (``solve`` applies compliance; ``_block`` formats one step). It uses
the dispatcher's shared state and helpers (``state``, ``faults``, ``circuit``, ``scenario``, ``_smu``,
``_channel_type``, ``_check_interlock``, ``_on_levels``, ``_current``, ``_sync_devices``) and the A/D converter
settings of ``CoreUnit`` (``integration_time``, ``noise_multiplier``). A second family that brings its own ``MM``
modes takes over ``MM``/``XE`` dispatch by mode. Manual references (Programming Guide Ed. 15, physical PDF pages):
``RI`` 501; ``RV`` 503; ``MM`` 470-471; ``CMM`` 380; ``DV`` 396; ``WV`` 568-569; ``WT`` 564-565; ``WM`` 552-553;
``XE`` 570; interlock in the high-voltage state 577.
``MM 10`` (sampling) triggers are handed to ``SamplingUnit._start_sampling`` (``units/sampling.py``, WP7.4).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import DUMMY_VALUE, Element, worst_status
from b1500_test_agent.transport.sim.units.base import DEFAULT_ICOMP, Measurement, Unsupported, handles

OVERRANGE = 1.15
"""Fixed current range overflow threshold, as a fraction of full scale (simulator convention)."""


@dataclass(frozen=True)
class Sweep:
    """``WV`` settings (PG PDF 568-569)."""

    channel: int
    mode: int
    vrange: int
    start: float
    stop: float
    steps: int
    icomp: float

    def values(self) -> list[float]:
        """Output values: linear or log, single (start→stop) or double (start→stop→start, 2·steps points)."""
        n = self.steps
        if n == 1:
            forward = [self.start]
        elif self.mode in (1, 3):
            forward = [self.start + (self.stop - self.start) * i / (n - 1) for i in range(n)]
        else:
            ratio = self.stop / self.start
            forward = [self.start * ratio ** (i / (n - 1)) for i in range(n)]
        return forward + forward[::-1] if self.mode in (3, 4) else forward


class SmuUnit:
    """SMU FLEX handlers and the measurement engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_smu_settings(self) -> None:
        """Measurement mode, ranging and sweep setup to their initial settings (PG Table 2-13, PDF 180)."""
        self._mm: tuple[int, list[int]] | None = None
        self._cmm: dict[int, int] = {}
        self._ri: dict[int, int] = {}
        self._rv: dict[int, int] = {}
        self._sweep: Sweep | None = None
        self._wt = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._wm = (1, 1)

    # -- ranges and modes ----------------------------------------------------------------------------------------------

    @handles("RI")
    def _cmd_ri(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        module = self._channel_type(channel) or ""
        if code != 0 and abs(code) not in flex.I_CODES.get(module, range(0)):
            raise flex.FlexError(flex.ERR_RANGE, f"RI {code} on {module}")
        self._ri[channel] = code

    @handles("RV")
    def _cmd_rv(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        if code not in flex.V_MEAS_CODES:
            raise flex.FlexError(flex.ERR_RANGE, f"RV {code}")
        self._rv[channel] = code

    @handles("MM")
    def _cmd_mm(self, cmd: flex.Command) -> None:
        """``MM 1|2|10,ch...``: spot, staircase sweep or sampling (``units/sampling.py``); other modes are
        unsupported (PDF 470-471)."""
        if not cmd.args:
            raise flex.FlexError(flex.ERR_TERMINATOR)
        mode = flex.integer(cmd.args[0])
        if not 1 <= mode <= 28:
            raise flex.FlexError(flex.ERR_PARAMETER)
        if mode not in (1, 2, 10):
            raise Unsupported(f"MM {mode}")
        channels = [self._smu(a) for a in cmd.args[1:]]
        if not 1 <= len(channels) <= 10 or len(set(channels)) != len(channels):
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT)
        self._mm = (mode, channels)

    @handles("CMM")
    def _cmd_cmm(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1, 2, 3):  # mode 4 is not available for HP/MP/HRSMU (PDF 380)
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._cmm[channel] = mode

    # -- sources -------------------------------------------------------------------------------------------------------

    @handles("DV")
    def _cmd_dv(self, cmd: flex.Command) -> None:
        """``DV chnum,vrange,voltage[,Icomp[,comp_polarity[,irange]]]`` (PDF 396)."""
        flex.arity(cmd, 3, 6)
        channel = self._smu(cmd.args[0])
        state = self.state.channels[channel]
        if not state.output_on:
            raise flex.FlexError(flex.ERR_OUTPUT_OFF)
        vrange = flex.integer(cmd.args[1])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"vrange {vrange}")
        voltage = flex.number(cmd.args[2])
        if abs(voltage) > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{voltage} V")
        icomp = flex.number(cmd.args[3]) if len(cmd.args) > 3 else state.icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(voltage):
            raise flex.FlexError(flex.ERR_DV_COMPLIANCE, f"Icomp {icomp}")
        polarity = flex.integer(cmd.args[4]) if len(cmd.args) > 4 else 0
        if polarity not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        irange = flex.integer(cmd.args[5]) if len(cmd.args) > 5 else 0
        module = self._channel_type(channel) or ""
        if irange != 0 and irange not in flex.I_CODES.get(module, range(0)):
            raise flex.FlexError(flex.ERR_RANGE, f"irange {irange}")
        self._check_interlock(voltage)
        state.voltage, state.icomp, state.comp_polarity = voltage, abs(icomp), polarity
        state.vrange, state.irange = vrange, irange

    @handles("WV")
    def _cmd_wv(self, cmd: flex.Command) -> None:
        """``WV chnum,mode,range,start,stop,step[,Icomp[,Pcomp]]`` (PDF 568-569); Pcomp is unsupported in v1."""
        flex.arity(cmd, 6, 8)
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (1, 2, 3, 4):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {mode}")
        vrange = flex.integer(cmd.args[2])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"range {vrange}")
        start, stop = flex.number(cmd.args[3]), flex.number(cmd.args[4])
        peak = max(abs(start), abs(stop))
        if peak > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} V")
        steps = flex.integer(cmd.args[5])
        if not 1 <= steps <= 10001:
            raise flex.FlexError(flex.ERR_PARAMETER, f"step {steps}")
        if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0)):
            raise flex.FlexError(flex.ERR_LOG_POLARITY)
        if len(cmd.args) > 7:
            raise Unsupported("WV power compliance (Pcomp)")
        icomp = flex.number(cmd.args[6]) if len(cmd.args) > 6 else self.state.channels[channel].icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(peak):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Icomp {icomp}")
        self._check_interlock(peak)
        self._sweep = Sweep(channel, mode, vrange, start, stop, steps, abs(icomp))

    @handles("WT")
    def _cmd_wt(self, cmd: flex.Command) -> None:
        """``WT hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`` (PDF 564-565)."""
        flex.arity(cmd, 2, 5)
        values = [flex.number(a) for a in cmd.args] + [0.0] * (5 - len(cmd.args))
        hold, delay, sdelay, tdelay, mdelay = values
        if not (0 <= hold <= 655.35 and 0 <= delay <= 65.535 and 0 <= sdelay <= 1.0 and 0 <= tdelay <= delay
                and 0 <= mdelay <= 65.535):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._wt = (hold, delay, sdelay, tdelay, mdelay)

    @handles("WM")
    def _cmd_wm(self, cmd: flex.Command) -> None:
        """``WM abort[,post]``: automatic abort 1 off / 2 on; post 1 start / 2 stop (PDF 552-553)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if abort not in (1, 2) or post not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._wm = (abort, post)

    # -- measurement ---------------------------------------------------------------------------------------------------

    def solve(self, levels: dict[int, float], icomps: dict[int, float]) -> tuple[dict[int, float], dict[int, float],
                                                                                    set[int]]:
        """Applied voltages, channel currents and the channels in compliance for programmed ``levels``.

        A channel whose |I| would exceed its compliance has its applied voltage bisected (between the programmed
        level and 0 V, or beyond 0 V when another biased terminal still drives more than Icomp there, e.g. through a
        gate-drain short) until |I| = Icomp; this repeats for the next channel in compliance. The devices are
        passive, so a channel's current rises monotonically with its own voltage.
        """
        applied = dict(levels)
        clamped: set[int] = set()
        for _ in range(len(applied)):
            currents = self._current(applied)
            over = [ch for ch in applied
                    if ch not in clamped and abs(currents.get(ch, 0.0)) > icomps[ch] * (1 + 1e-12)]
            if not over:
                break
            channel = max(over, key=lambda ch: abs(currents[ch]) / icomps[ch])
            applied[channel] = self._bisect(applied, channel, icomps[channel])
            clamped.add(channel)
        return applied, self._current(applied), clamped

    def _bisect(self, applied: dict[int, float], channel: int, icomp: float) -> float:
        def current(voltage: float) -> float:
            trial = dict(applied)
            trial[channel] = voltage
            return self._current(trial).get(channel, 0.0)

        sign = 1.0 if current(applied[channel]) >= 0 else -1.0  # direction of the excess current

        def excess(voltage: float) -> float:
            return sign * current(voltage) - icomp

        lo, hi = 0.0, applied[channel]
        step = max(abs(hi), 0.1)
        while excess(lo) > 0:  # 0 V still drives more than Icomp: move against the current's direction
            if step > 4 * flex.SMU_MAX_V:
                return lo  # cannot be limited within the output range (never reached by passive devices)
            hi, lo = lo, lo - sign * step
            step *= 2
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if excess(mid) > 0:
                hi = mid
            else:
                lo = mid
            if abs(hi - lo) < 1e-12:
                break
        return lo

    @handles("XE")
    def _cmd_xe(self, cmd: flex.Command) -> None:
        """``XE``: trigger the ``MM`` measurement (PDF 570); errors 214, 220, 200."""
        flex.arity(cmd, 0, 0)
        if self._mm is None:
            raise flex.FlexError(flex.ERR_NO_MM)
        mode, channels = self._mm
        if mode == 10:
            self._start_sampling(channels)
            return
        sweep = self._sweep if mode == 2 else None
        if mode == 2 and sweep is None:
            raise flex.FlexError(flex.ERR_NO_SWEEP)
        for channel in [*channels, *([sweep.channel] if sweep else [])]:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        self._measurement = self._measure(channels, sweep, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    def _measure(self, channels: list[int], sweep: Sweep | None, t0: float) -> Measurement:
        factor = self.faults.slow_factor()
        hold, delay, sdelay = self._wt[0], self._wt[1], self._wt[2]
        tmeas = {ch: self.integration_time(ch) for ch in channels}
        meas_total = sum(tmeas.values())
        values: list[float | None] = list(sweep.values()) if sweep else [None]
        levels0 = self._on_levels()
        icomps = {ch: self._icomp(ch) for ch in levels0}
        if sweep:
            icomps[sweep.channel] = sweep.icomp
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        aborted = False
        zero_at: float | None = None
        last = len(values) - 1
        period = delay + max(meas_total, sdelay)
        for i, value in enumerate(values):
            if sweep:  # hold, then per step: force, wait delay, measure; next step after max(meas, Sdelay)
                meas_start, nominal_end = hold + i * period + delay, hold + (i + 1) * period
            else:
                meas_start, nominal_end = 0.0, meas_total
            end = t0 + factor * nominal_end
            step_ends.append(end)
            stamp = t0 + factor * meas_start - self._timer_zero
            levels = dict(levels0)
            if sweep and value is not None:
                levels[sweep.channel] = value
            if not aborted and self.faults.interlock_opens_at(i):
                self._interlock_open = True
            if not aborted and self.interlock_open() and self._high_voltage(levels):
                # interlock opened in the high-voltage state: all outputs to 0 V, error 202 (PG PDF 577)
                self._queue_error(flex.ERR_INTERLOCK)
                zero_at = end
                aborted = True
            if aborted:
                blocks.append(self._dummy_block(channels, sweep, stamp, i == last))
                continue
            block, statuses, applied = self._block(channels, sweep, value, levels, icomps, tmeas, stamp, i, last, rng)
            blocks.append(block)
            if self.circuit.has_state:  # the step's voltages act on the device before the next step
                self.circuit.commit(applied)
                device_states.append(self.circuit.export_state())
            if self._wm[0] == 2 and any(s in "CTVX" for s in statuses):
                aborted = True  # automatic abort: later steps carry dummy data (PDF 553)
        post: float | None = None
        if sweep is not None:
            post = sweep.start if (self._wm[1] == 1 or aborted) else sweep.stop
        self._sync_devices()
        return Measurement(t0, step_ends[-1], step_ends, blocks, sweep, post, zero_at, device_states)

    def _block(self, channels: list[int], sweep: Sweep | None, value: float | None, levels: dict[int, float],
               icomps: dict[int, float], tmeas: dict[int, float], stamp: float, step: int, last: int,
               rng: random.Random) -> tuple[list[str], list[str], dict[int, float]]:
        applied, currents, clamped = self.solve(levels, icomps)
        forced = {canonical_channel(ch) for ch in self.faults.compliance_channels(step)}
        limited = clamped | forced
        oscillating = self.faults.oscillating(step)
        texts: list[str] = []
        statuses: list[str] = []
        offset = 0.0
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            status = "C" if channel in limited else ("T" if limited else "N")
            if quantity == "I":
                reading = currents.get(channel, 0.0)
                if channel in forced:
                    sign = reading if reading != 0 else (applied.get(channel, 0.0) or 1.0)
                    reading = math.copysign(icomps.get(channel, DEFAULT_ICOMP), sign)
                else:
                    reading += self._noise(channel, reading, rng)
                code = self._ri.get(channel, 0)
                if code < 0 and abs(reading) > OVERRANGE * flex.current_range(code):
                    status = worst_status([status, "V"])
            else:
                reading = applied.get(channel, 0.0)
            if oscillating:
                status = worst_status([status, "X"])
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp + offset).text())
            texts.append(Element(status, channel, quantity, reading).text())
            statuses.append(status)
            offset += tmeas[channel]
        if self.faults.garbage_at(step):
            texts[1 if self._tsc else 0] = GARBAGE_ELEMENT
        if sweep is not None and value is not None and self._fmt_mode == 1:
            texts.append(Element("E" if step == last else "W", sweep.channel, "V", value).text())
        return texts, statuses, applied

    def _dummy_block(self, channels: list[int], sweep: Sweep | None, stamp: float, is_last: bool) -> list[str]:
        texts: list[str] = []
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp).text())
            texts.append(Element("V", channel, quantity, DUMMY_VALUE).text())
        if sweep is not None and self._fmt_mode == 1:
            texts.append(Element("E" if is_last else "W", sweep.channel, "V", DUMMY_VALUE).text())
        return texts

    def _noise(self, channel: int, current: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = self.noise_multiplier(channel) * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0
