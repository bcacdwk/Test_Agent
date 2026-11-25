"""SMU sampling unit of the simulator (``MM 10``): ``MCC``, ``ML``, ``MT``, ``MSC``, ``MV``, ``MI``, ``TSR`` and the
sampling engine (blueprint v2 4.1, kind ``smu_sampling``).

``SamplingUnit`` is a mixin of ``SimInstrument``. ``SmuUnit`` hands ``MM 10`` triggers to ``_start_sampling``; the
engine evaluates the whole measurement at ``XE`` on the scenario circuit, in virtual time, as the B1500 runs it
(Programming Guide Ed. 15, physical PDF pages: sampling operation 112-114 and ``MT`` 474-476; ``MCC`` 461; ``MI``
468-469; ``ML`` 469-470; ``MSC`` 472-473; ``MV`` 477-478; ``TSR`` 539-540; data format 46, 49):

- trigger at ``t0``: ``MV``/``MI`` sources force their base value, at ``t = t0 + h_base`` their bias value; DC
  (``DV``/``DI``) sources keep their level. Samples fall on the grid ``t + h_bias + (index - 1) x interval``; a
  sample that would start while the channels are still measuring the previous one is skipped (its index is not
  returned: PDF 49), so a slow measurement (``slow`` fault) shows index gaps. Linear mode holds ``number``
  samples; log mode (``ML`` 2-7) holds the first ``number`` distinct indices ``round(10^(j/density))``
  (TODO(verify) at L5: the instrument's choice of the held points). Intervals below 2 ms measure the channels in
  parallel and stop at ``h_bias + interval x number`` even with fewer samples.
- If the channels' integration time exceeds the interval, the instrument shortens the averaging to keep the
  interval (PDF 475): the simulator measures for at most the interval and raises the noise to that of the shorter
  integration.
- Dynamic devices evolve between samples (``Circuit.advance`` under the voltages applied, split at the bias step);
  each sample is a quasi-static solve with compliance (``SmuUnit.solve``); current sources (``MI``, ``DI``) are
  solved for the voltage that carries their current within Vcomp (status ``C`` when Vcomp is reached). The
  ``breakdown_at`` fault breaks the dielectrics at its time.
- ``MSC 2``: compliance (``C``/``T``), overflow (``V``) or oscillation (``X``) on a sample aborts: later samples are
  ``199.999E+99`` with status ``V`` and the sources go to their base value at once; a normal end leaves them at the
  ``MSC`` post value (bias by default). An ``AB`` also returns them to base.
- Data: per sample ``[Sampling_no,]`` (FMT mode 1; status ``N``, the first measured channel's letter: an assumption,
  the PG does not print it) then per measured channel ``[Time,]Data`` (``TSC 1``; time since the last ``TSR``).

The simulator keeps DC state as voltages: after the measurement an ``MI`` channel holds the voltage its post current
produced (the cleanup's ``DZ`` zeroes it like any other output). ``TSR chnum`` (timer reset at a later ``DV``) is
not simulated (error 100, logged ``unsupported``).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import Element, worst_status
from b1500_test_agent.transport.sim.units.base import DEFAULT_ICOMP, Measurement, Unsupported, handles
from b1500_test_agent.transport.sim.units.core import NOISE_MULTIPLIERS

LOG_DENSITY = {2: 10, 3: 25, 4: 50, 5: 100, 6: 250, 7: 500}
"""``ML`` log modes → data per decade (PDF 470)."""

FAST_INTERVAL_S = 0.002
"""Below this interval the sampling is linear only, the channels measure in parallel and ``h_bias`` may be negative
(PDF 474-475)."""

MAX_HOLD_S = 655.35
MT_INITIAL = (0.0, 0.002, 1000, 0.0)
"""``MT`` initial setting: bias hold 0 s, interval 2 ms, 1000 points, base hold 0 s (PDF 177/180, 475)."""

MAX_SMU_CURRENT_A = 0.1
"""Largest |I| an MP/HRSMU forces (Table 4-8, 100 mA range)."""

ABORT_STATUSES = frozenset("CTVX")
"""Sample statuses that stop an ``MSC 2`` measurement: compliance (this or another channel), overflow, oscillation."""


@dataclass(frozen=True)
class SamplingSourceState:
    """One ``MV`` (``quantity`` V; ``compliance`` = Icomp, A) or ``MI`` (I; Vcomp, V) synchronous source."""

    channel: int
    quantity: str
    out_range: int
    base: float
    bias: float
    compliance: float

    def level(self, after_step: bool) -> float:
        return self.bias if after_step else self.base


def log_indices(density: int, number: int) -> list[int]:
    """The first ``number`` distinct sampling indices ``round(10^(j/density))``, j = 0, 1, ... (log sampling)."""
    held: list[int] = []
    j = 0
    while len(held) < number:
        index = round(10.0 ** (j / density))
        j += 1
        if not held or index > held[-1]:
            held.append(index)
    return held


class SamplingUnit:
    """Sampling handlers and engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_sampling_settings(self) -> None:
        """Sampling setup to its initial settings (PG Table 2-13, PDF 180): linear, ``MT`` initial, abort off with
        the bias value after the measurement, no sampling sources."""
        self._ml = 1
        self._mt: tuple[float, float, int, float] = MT_INITIAL
        self._msc: tuple[int, int] = (1, 2)
        self._sampling_sources: dict[int, SamplingSourceState] = {}

    # -- setup commands ------------------------------------------------------------------------------------------------

    @handles("MCC")
    def _cmd_mcc(self, cmd: flex.Command) -> None:
        """``MCC [chnum...]``: clear the ``MV``/``MI``/``MSP`` sources (all, or the listed channels; PDF 461)."""
        if len(cmd.args) > 15:
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT)
        if not cmd.args:
            self._sampling_sources.clear()
            return
        for arg in cmd.args:
            self._sampling_sources.pop(self._channel(arg), None)

    @handles("ML")
    def _cmd_ml(self, cmd: flex.Command) -> None:
        """``ML mode``: 1 linear, 2-7 log with 10-500 data per decade (PDF 469-470)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode != 1 and mode not in LOG_DENSITY:
            raise flex.FlexError(flex.ERR_PARAMETER, f"ML {mode}")
        self._ml = mode

    @handles("MT")
    def _cmd_mt(self, cmd: flex.Command) -> None:
        """``MT h_bias,interval,number[,h_base]`` (PDF 474-476); values rounded to the instrument resolution."""
        flex.arity(cmd, 3, 4)
        h_bias, interval = flex.number(cmd.args[0]), flex.number(cmd.args[1])
        number = flex.integer(cmd.args[2])
        h_base = flex.number(cmd.args[3]) if len(cmd.args) > 3 else 0.0
        if not 0.0001 <= interval <= 65.535 or not 1 <= number <= 100001 or not 0 <= h_base <= MAX_HOLD_S:
            raise flex.FlexError(flex.ERR_PARAMETER, f"MT {','.join(cmd.args)}")
        fast = interval < FAST_INTERVAL_S
        if h_bias < 0 and not (fast and -0.09 <= h_bias <= -0.0001) or h_bias > MAX_HOLD_S:
            raise flex.FlexError(flex.ERR_PARAMETER, f"MT h_bias {h_bias}")
        interval = round(interval, 5 if fast else 3)
        h_bias = round(h_bias, 4) if h_bias < 0 else round(h_bias, 2)
        self._mt = (h_bias, interval, number, round(h_base, 2))

    @handles("MSC")
    def _cmd_msc(self, cmd: flex.Command) -> None:
        """``MSC abort[,post]``: abort 1 off / 2 on; post 1 base / 2 bias (initial; PDF 472-473)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 2
        if abort not in (1, 2) or post not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._msc = (abort, post)

    @handles("MV")
    def _cmd_mv(self, cmd: flex.Command) -> None:
        """``MV chnum,vrange,base,bias[,Icomp]``: synchronous voltage source (PDF 477-478); replaces an ``MI``."""
        flex.arity(cmd, 4, 5)
        channel = self._smu(cmd.args[0])
        vrange = flex.integer(cmd.args[1])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"vrange {vrange}")
        base, bias = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        peak = max(abs(base), abs(bias))
        if peak > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} V")
        icomp = flex.number(cmd.args[4]) if len(cmd.args) > 4 else self.state.channels[channel].icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(peak):
            raise flex.FlexError(flex.ERR_DV_COMPLIANCE, f"Icomp {icomp}")
        self._check_interlock(peak)
        self._sampling_sources[channel] = SamplingSourceState(channel, "V", vrange, base, bias, abs(icomp))

    @handles("MI")
    def _cmd_mi(self, cmd: flex.Command) -> None:
        """``MI chnum,irange,base,bias[,Vcomp]``: synchronous current source (PDF 468-469); replaces an ``MV``."""
        flex.arity(cmd, 4, 5)
        channel = self._smu(cmd.args[0])
        irange = flex.integer(cmd.args[1])
        if irange != 0 and irange not in self._i_codes(channel):  # the ASU ranges too (WP7.1)
            raise flex.FlexError(flex.ERR_RANGE, f"irange {irange}")
        base, bias = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        if base * bias < 0 or max(abs(base), abs(bias)) > MAX_SMU_CURRENT_A:
            raise flex.FlexError(flex.ERR_PARAMETER, f"MI base {base} bias {bias}")
        previous = self._sampling_sources.get(channel)
        vcomp = flex.number(cmd.args[4]) if len(cmd.args) > 4 else (
            previous.compliance if previous is not None and previous.quantity == "I" else None)
        if vcomp is None or abs(vcomp) > flex.SMU_MAX_V:
            raise flex.FlexError(flex.ERR_DV_COMPLIANCE, f"Vcomp {vcomp}")
        self._check_interlock(abs(vcomp))
        self._sampling_sources[channel] = SamplingSourceState(channel, "I", irange, base, bias, abs(vcomp))

    @handles("TSR")
    def _cmd_tsr(self, cmd: flex.Command) -> None:
        """``TSR``: clear the timer count now (PDF 539-540). The deferred ``TSR chnum`` form is not simulated."""
        flex.arity(cmd, 0, 1)
        if cmd.args:
            raise Unsupported("TSR chnum")
        self._timer_zero = self._now()

    # -- trigger -------------------------------------------------------------------------------------------------------

    def _start_sampling(self, channels: list[int]) -> None:
        """``XE`` with ``MM 10``: check the setup, evaluate the measurement, mark the instrument busy until its end."""
        sources = dict(self._sampling_sources)
        for channel in [*channels, *sources]:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        _, interval, number, _ = self._mt
        if self._ml in LOG_DENSITY:
            if interval < FAST_INTERVAL_S or number > 1 + 11 * LOG_DENSITY[self._ml]:
                raise flex.FlexError(flex.ERR_PARAMETER, f"log sampling with interval {interval} and {number} points")
        elif number > 100001 // len(channels) or (
                interval < FAST_INTERVAL_S and interval < 0.0001 + 0.00002 * (len(channels) - 1) - 1e-12):
            raise flex.FlexError(flex.ERR_PARAMETER, f"MT {number} points at {interval} s for {len(channels)} "
                                 "channel(s)")
        self._measurement = self._measure_sampling(channels, sources, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    # -- engine --------------------------------------------------------------------------------------------------------

    def _sample_times(self, t_origin: float, t0: float, period: float) -> list[tuple[int, float]]:
        """``(index, start time)`` of every held sample (module docstring: grid, skipped indices, log, fast stop)."""
        h_bias, interval, number, _ = self._mt
        first = t_origin + h_bias

        def grid(k: int) -> float:
            return first + (k - 1) * interval

        samples: list[tuple[int, float]] = []
        free = t0
        if self._ml in LOG_DENSITY:
            for target in log_indices(LOG_DENSITY[self._ml], number):
                k = max(target, samples[-1][0] + 1 if samples else 1)
                while grid(k) < free - 1e-12:
                    k += 1
                samples.append((k, grid(k)))
                free = grid(k) + period
            return samples
        fast = interval < FAST_INTERVAL_S
        stop = first + interval * number
        k = 1
        while len(samples) < number:
            t = grid(k)
            if fast and t >= stop - 1e-12:
                break  # fast linear sampling stops at h_bias + interval x number (PDF 476)
            if t >= free - 1e-12 and t >= t0 - 1e-12:
                samples.append((k, t))
                free = t + period
            k += 1
        return samples

    def _sampling_levels(self, levels0: dict[int, float], currents0: dict[int, tuple[float, float]],
                         sources: dict[int, SamplingSourceState],
                         after_step: bool) -> tuple[dict[int, float], dict[int, tuple[float, float]]]:
        """Voltage levels (``DV`` and ``MV``) and current sources ``{channel: (current, Vcomp)}`` (``DI`` and ``MI``)
        at one moment."""
        levels = dict(levels0)
        currents = {ch: forced for ch, forced in currents0.items() if ch not in sources}
        for channel, source in sources.items():
            if source.quantity == "V":
                levels[channel] = source.level(after_step)
            else:
                currents[channel] = (source.level(after_step), source.compliance)
                levels.pop(channel, None)
        return levels, currents

    def _solve_sampling(self, levels: dict[int, float], icomps: dict[int, float],
                        currents: dict[int, tuple[float, float]]) -> tuple[dict[int, float], dict[int, float],
                                                                             set[int]]:
        """``SmuUnit.solve`` with current sources: each ``MI``/``DI`` channel gets the voltage (within Vcomp) that
        carries its current, by bisection on its own voltage (passive devices: monotonic), then the voltage sources'
        compliance is applied. Returns applied voltages, channel currents and the channels in compliance."""
        trial = dict(levels)
        limited: set[int] = set()
        for channel in currents:
            trial[channel] = 0.0
        for _ in range(3 if len(currents) > 1 else 1):
            for channel, (target, vcomp) in currents.items():
                trial[channel], at_limit = self._voltage_for_current(trial, channel, target, vcomp)
                if at_limit:
                    limited.add(channel)
                else:
                    limited.discard(channel)
        comps = dict(icomps)
        for channel, (target, _) in currents.items():
            comps[channel] = max(abs(target) * (1 + 1e-6), 1e-15)
        applied, measured, clamped = self.solve(trial, comps)
        return applied, measured, clamped | limited

    def _voltage_for_current(self, levels: dict[int, float], channel: int, target: float,
                             vcomp: float) -> tuple[float, bool]:
        def current(voltage: float) -> float:
            trial = dict(levels)
            trial[channel] = voltage
            return self._current(trial).get(channel, 0.0)

        lo, hi = -vcomp, vcomp
        if target >= current(hi):
            return hi, target > current(hi)
        if target <= current(lo):
            return lo, target < current(lo)
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            if current(mid) < target:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-12:
                break
        return 0.5 * (lo + hi), False

    def _evolve(self, start: float, end: float, t_origin: float, applied: dict[int, float],
                step_levels: dict[int, float], icomps: dict[int, float],
                step_currents: dict[int, tuple[float, float]]) -> dict[int, float]:
        """Hold the outputs from ``start`` to ``end``: dynamic devices evolve under ``applied``; at the bias step
        (``t_origin``) the applied voltages are re-solved for the bias levels. Returns the voltages applied at
        ``end``."""
        if not self.circuit.dynamic or end <= start:
            return applied
        if start < t_origin < end:
            self.circuit.advance(t_origin - start, applied)
            applied = self._solve_sampling(step_levels, icomps, step_currents)[0]
            start = t_origin
        self.circuit.advance(end - start, applied)
        return applied

    def _sampling_noise(self, channel: int, current: float, multiplier: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = multiplier * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0

    def _break_down(self, devices: list[str | None]) -> None:
        for name, device in self.circuit.devices.items():
            if any(d is None or d == name for d in devices) and hasattr(device, "break_down"):
                device.break_down()

    def _measure_sampling(self, channels: list[int], sources: dict[int, SamplingSourceState],
                          t0: float) -> Measurement:
        _, interval, _, h_base = self._mt
        abort_enabled, post = self._msc[0] == 2, self._msc[1]
        fast = interval < FAST_INTERVAL_S
        factor = self.faults.slow_factor()
        t_origin = t0 + h_base
        nominal = {ch: self.integration_time(ch) for ch in channels}
        total = max(nominal.values()) if fast else sum(nominal.values())
        scale = min(1.0, interval / total) if total > 0 else 1.0  # MT: averaging shortened to keep the interval
        tmeas = {ch: t * scale for ch, t in nominal.items()}
        multipliers = {ch: next(m for limit, m in NOISE_MULTIPLIERS if t * flex.LINE_FREQUENCY_HZ < limit)
                       for ch, t in tmeas.items()}
        period = factor * (max(tmeas.values()) if fast else sum(tmeas.values()))
        planned = self._sample_times(t_origin, t0, period)
        levels0 = self._on_levels()
        currents0 = self._on_currents()
        icomps = {ch: self._icomp(ch) for ch in levels0}
        for channel, source in sources.items():
            if source.quantity == "V":
                icomps[channel] = source.compliance
        base_levels, base_currents = self._sampling_levels(levels0, currents0, sources, after_step=False)
        bias_levels, bias_currents = self._sampling_levels(levels0, currents0, sources, after_step=True)
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        applied = self._solve_sampling(base_levels, icomps, base_currents)[0]
        previous = t0
        aborted = False
        zero_at: float | None = None
        end = t0
        for position, (index, t) in enumerate(planned):
            stamp = t - self._timer_zero
            if aborted:  # after an automatic abort: dummy data, no time (PDF 473)
                blocks.append(self._dummy_sample(channels, index, stamp, tmeas, fast))
                step_ends.append(end)
                continue
            after_step = t >= t_origin
            applied = self._evolve(previous, t, t_origin, applied, bias_levels, icomps, bias_currents)
            previous = t
            due = self.faults.breakdowns_due(t)
            if due:
                self._break_down(due)
            levels, currents = (bias_levels, bias_currents) if after_step else (base_levels, base_currents)
            if self.faults.interlock_opens_at(position):
                self._interlock_open = True
            forced_v = {**levels, **{ch: vcomp for ch, (_, vcomp) in currents.items()}}
            if self.interlock_open() and self._high_voltage(forced_v):
                self._interlock_trip()  # all outputs to 0 V, error 202 (PG PDF 577)
                zero_at = end = t
                aborted = True
                blocks.append(self._dummy_sample(channels, index, stamp, tmeas, fast))
                step_ends.append(end)
                continue
            applied, measured, clamped = self._solve_sampling(levels, icomps, currents)
            texts, statuses = self._sample_texts(channels, index, stamp, tmeas, fast, applied, measured, clamped,
                                                 icomps, currents, multipliers, position, rng)
            blocks.append(texts)
            end = t + period
            step_ends.append(end)
            if self.circuit.has_state:
                self.circuit.commit(applied)
                device_states.append(self.circuit.export_state())
            if abort_enabled and any(s in ABORT_STATUSES for s in statuses):
                aborted = True
        if not aborted and planned:  # the outputs stay on while the last sample is measured
            self._evolve(previous, end, t_origin, applied, bias_levels, icomps, bias_currents)
        self._sync_devices()
        normal = {ch: s.level(post == 2) for ch, s in sources.items()}
        at_base = {ch: s.base for ch, s in sources.items()}
        levels_after = at_base if aborted else normal
        measurement = Measurement(t0, end, step_ends, blocks, None, None, zero_at, device_states)
        measurement.source_levels = self._held_voltages(levels_after, sources, levels0, currents0, icomps)
        measurement.abort_source_levels = self._held_voltages(at_base, sources, levels0, currents0, icomps)
        return measurement

    def _held_voltages(self, levels: dict[int, float], sources: dict[int, SamplingSourceState],
                       levels0: dict[int, float], currents0: dict[int, tuple[float, float]],
                       icomps: dict[int, float]) -> dict[int, tuple[float, float]]:
        """``{channel: (voltage, compliance)}`` each synchronous source holds after the measurement: an ``MV`` its
        level; an ``MI`` the voltage its current produces (within Vcomp, with the ``DI`` outputs at their current)."""
        held: dict[int, tuple[float, float]] = {}
        dc = {ch: v for ch, v in levels0.items() if ch not in sources}
        dc_amps = {ch: forced for ch, forced in currents0.items() if ch not in sources}
        volts = {ch: levels[ch] for ch, s in sources.items() if s.quantity == "V"}
        amps = {ch: (levels[ch], s.compliance) for ch, s in sources.items() if s.quantity == "I"}
        applied = self._solve_sampling({**dc, **volts}, icomps, {**dc_amps, **amps})[0] if amps else {}
        for channel, source in sources.items():
            if source.quantity == "V":
                held[channel] = (levels[channel], source.compliance)
            else:
                held[channel] = (applied.get(channel, 0.0), max(abs(levels[channel]), DEFAULT_ICOMP))
        return held

    def _sample_texts(self, channels: list[int], index: int, stamp: float, tmeas: dict[int, float], fast: bool,
                      applied: dict[int, float], measured: dict[int, float], clamped: set[int],
                      icomps: dict[int, float], currents: dict[int, tuple[float, float]],
                      multipliers: dict[int, float], position: int, rng: random.Random) -> tuple[list[str], list[str]]:
        forced = {canonical_channel(ch) for ch in self.faults.compliance_channels(position)}
        limited = clamped | forced
        oscillating = self.faults.oscillating(position)
        texts: list[str] = []
        if self._fmt_mode != 0:
            texts.append(Element("N", channels[0], "X", float(index)).text())
        statuses: list[str] = []
        offset = 0.0
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            status = "C" if channel in limited else ("T" if limited else "N")
            if quantity == "I":
                reading = currents[channel][0] if channel in currents and channel not in limited \
                    else measured.get(channel, 0.0)
                if channel in forced:
                    sign = reading if reading != 0 else (applied.get(channel, 0.0) or 1.0)
                    reading = math.copysign(icomps.get(channel, DEFAULT_ICOMP), sign)
                else:
                    reading += self._sampling_noise(channel, reading, multipliers[channel], rng)
                code = self._ri.get(channel, 0)
                if code < 0 and abs(reading) > 1.15 * flex.current_range(code):
                    status = worst_status([status, "V"])
            else:
                reading = applied.get(channel, 0.0)
            if oscillating:
                status = worst_status([status, "X"])
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp + offset).text())
            texts.append(Element(status, channel, quantity, reading).text())
            statuses.append(status)
            if not fast:
                offset += tmeas[channel]
        if self.faults.garbage_at(position):
            texts[(1 if self._fmt_mode != 0 else 0) + (1 if self._tsc else 0)] = GARBAGE_ELEMENT
        return texts, statuses

    def _dummy_sample(self, channels: list[int], index: int, stamp: float, tmeas: dict[int, float],
                      fast: bool) -> list[str]:
        texts: list[str] = []
        if self._fmt_mode != 0:
            texts.append(Element("N", channels[0], "X", float(index)).text())
        offset = 0.0
        for channel in channels:
            quantity = "V" if self._cmm.get(channel, 0) in (2, 3) else "I"
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp + offset).text())
            texts.append(Element("V", channel, quantity, 0.0).text())
            if not fast:
                offset += tmeas[channel]
        return texts
