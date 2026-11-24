"""SMU search unit of the simulator (``MM 14`` linear search, ``MM 15`` binary search, ``MM 9`` quasi-pulsed spot):
``LSV``, ``LSI``, ``LGV``, ``LGI``, ``LSM``, ``LSTM``, ``LSSV``, ``LSSI``, ``LSVM``, ``BSV``, ``BSI``, ``BGV``, ``BGI``,
``BSM``, ``BST``, ``BSSV``, ``BSSI``, ``BSVM``, ``BDV``, ``BDT``, ``BDM`` and the search engine (blueprint v2 4.1,
kind ``smu_search``, WP7.5).

``SearchUnit`` is a mixin of ``SimInstrument``. ``SmuUnit._cmd_mm`` accepts ``MM 9[,ch]``, ``MM 14`` and ``MM 15``
and ``SmuUnit._cmd_xe`` hands their triggers to ``_start_search``. Manual references (Programming Guide Ed. 15,
physical PDF pages): operation MM 9 p106-107, MM 15 p108-109, MM 14 p110-111, synchronous output p132, automatic abort
p134; data p47 (``Data_search[,Data_sense]``), status Table 1-10 p53; ``BDM`` 364; ``BDT``/``BDV`` 365-366; ``BGI``
366-367; ``BGV`` 367-369; ``BSI`` 369; ``BSM`` 370-372; ``BSSI`` 372-373; ``BSSV`` 373-374; ``BST``/``BSV`` 374-375;
``BSVM`` 375; ``LGI`` 443; ``LGV`` 444; ``LSI`` 453-454; ``LSM`` 454-455; ``LSSI`` 455-456; ``LSSV`` 456-457;
``LSTM``/``LSV`` 459-460; ``LSVM`` 460; errors 270-279 (p581-582), 610 (p584).

Engine (evaluated at ``XE`` in virtual time; hold, then per measured point the delay and the monitor's integration
time):

- Linear: the source forces ``start + k x step`` (k = 0 ... while not beyond stop); the search ends at the first step
  whose monitor reading satisfies the ``LGI``/``LGV`` judgement (``Data_search`` status ``N``); with the automatic
  abort on, a step with compliance (``C``/``T``), overflow (``V``) or oscillation (``X``) that does not satisfy it
  stops the search (``S``); no step satisfying it: ``G`` with the last source value.
- Binary: normal mode measures at start and stop (a target outside their readings: ``G``), then at stop -/+ D/2;
  cautious mode at start, then start +/- D/2; every next point halves the change towards the side whose readings
  bracket the target (a monotonic response). Limit mode ends within ``target +/- limit`` (``N``) or when the change
  falls below the output resolution (``G``); repeat mode after ``repeats`` output changes (``N``, the point closest to
  the target). The automatic abort as linear. The ``BGI``/``BGV`` re-search between the last value and start/stop
  for non-monotonic responses (p367) is not simulated.
- Synchronous source: ``polarity x search value + offset`` at every point, same output mode.
- After the search the sources force start, stop or the last value (``LSM``/``BSM`` post); after an automatic abort
  (``S``) or ``AB`` their start values (p134).
- Quasi-pulsed (MM 9): after the hold at start the source ramps towards stop; the settling detection stops where the
  source first reaches its compliance (the first programmed value at which ``solve`` limits the source; found on a
  5 mV grid, then bisected to 1 nV) or at stop. Status ``C`` (compliance, the breakdown), ``N`` (reached stop), ``S``
  (compliance before a 10 V change from start, p53); the reading after the delay is the detection voltage (``BDM`` mode
  0) or the source current (mode 1, the compliance value at a detection) of the measurement channel; then the source
  returns to start. Ramp time ``|X - start| / slew`` with 60 V/ms (short) or 6 V/ms (long).

Simulator conventions (``TODO(verify)`` at bring-up stages L5/L9): the programmed level of a search step (and the
quasi-pulse at the detection) is committed to stateful devices when the source is limited, because an abrupt
breakdown (``dielectric``) happens on the way to it and the compliance acts only afterwards; a reading after a hard
breakdown is the detection voltage (the instrument might read the collapsed, compliance-limited voltage); ``G`` of
MM 9 (detection time over 3 s / 12 s) and the slew-rate ``S`` are not produced; the search source's output
resolution is 5e-5 of its range (Tables 4-6, 4-7 of the PG: e.g. 100 uV on the 2 V range).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import Element, worst_status
from b1500_test_agent.transport.sim.units.base import Measurement, handles
from b1500_test_agent.transport.sim.units.smu import force_source, max_vcomp

SEARCH_MODES = frozenset({9, 14, 15})
"""``MM 9`` quasi-pulsed spot, ``MM 14`` linear search, ``MM 15`` binary search (Table 4-28, PDF 471)."""

LINEAR_MAX_STEPS = 1001
"""``LSV``/``LSI``: at most 1001 search steps (PDF 460)."""

BDV_MIN_SPAN_V = 10.0
"""``BDV``: ``|start - stop|`` 10 V or more (PDF 365); a compliance within 10 V of start reads ``S`` (PDF 53)."""

QUASI_SLEW_V_PER_S = {0: 6.0e4, 1: 6.0e3}
"""Quasi-pulse ramp rate by ``BDM`` interval (short, long): 0 to 100 V in about 1.7 ms (PDF 366) and ten times
slower for the long interval (simulator convention)."""

QUASI_GRID_V = 5e-3
"""Scan grid of the quasi-pulse ramp before the bisection of the detection voltage."""

RESOLUTION_FRACTION = 5e-5
"""Output resolution of an SMU range as a fraction of its full scale (Tables 4-6/4-7, PDF 341-342)."""

V_RANGES = (0.5, 2.0, 5.0, 20.0, 40.0, 100.0)
"""MP/HRSMU voltage output ranges (Table 4-7, PDF 342)."""

ABORT_STATUSES = frozenset("CTVX")

ERR_NO_SEARCH_SOURCE = 270
ERR_NO_SEARCH_MONITOR = 271
ERR_SEARCH_SYNC_MODE = 273
ERR_SEARCH_TARGET = 275
ERR_SEARCH_START_STOP = 276
ERR_SEARCH_STEP = 277
ERR_SEARCH_SYNC_CHANNEL = 278
ERR_SEARCH_MONITOR_SIDE = 279
ERR_NO_QUASI_SOURCE = 610


@dataclass(frozen=True)
class SearchOut:
    """A search source (``LSV``/``LSI``/``BSV``/``BSI``) or the quasi-pulse source (``BDV``, ``step`` ``None``)."""

    channel: int
    source: str
    out_range: int
    start: float
    stop: float
    comp: float
    step: float | None = None

    def values(self) -> list[float]:
        """Linear search: the output of every step (not beyond stop)."""
        assert self.step is not None
        count = math.floor(abs(self.stop - self.start) / abs(self.step) + 1e-9) + 1
        return [self.start + k * self.step for k in range(count)]


@dataclass(frozen=True)
class SearchSync:
    """A synchronous search source: ``polarity x search + offset`` (``LSSV``/``LSSI``/``BSSV``/``BSSI``)."""

    channel: int
    source: str
    polarity: int
    offset: float
    comp: float

    def value(self, search: float) -> float:
        return self.polarity * search + self.offset


@dataclass(frozen=True)
class SearchMon:
    """A search monitor (``LGI``/``LGV``/``BGI``/``BGV``): ``mode`` (linear: 0 ``<=``, 1 ``>=``; binary: 0 limit,
    1 repeat) and ``condition`` (binary: the limit or the repeat count)."""

    channel: int
    quantity: str
    mode: int
    condition: float
    out_range: int
    target: float


@dataclass
class SearchPoint:
    """One measured point of a search: the source value, the monitor reading and every involved channel's status."""

    value: float
    reading: float
    status: str
    statuses: dict[int, str]


class SearchUnit:
    """Search handlers and engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_search_settings(self) -> None:
        """Search and quasi-pulse setup to their initial settings (PG Table 2-13, PDF 180)."""
        self._lstm: tuple[float, float] = (0.0, 0.0)
        self._lsm: tuple[int, int] = (1, 1)
        self._lsvm = 0
        self._lgx: SearchMon | None = None
        self._lsx: SearchOut | None = None
        self._lssx: SearchSync | None = None
        self._bst: tuple[float, float] = (0.0, 0.0)
        self._bsm: tuple[int, int, int] = (0, 1, 1)
        self._bsvm = 0
        self._bgx: SearchMon | None = None
        self._bsx: SearchOut | None = None
        self._bssx: SearchSync | None = None
        self._bdt: tuple[float, float] = (0.0, 0.0)
        self._bdm: tuple[int, int] = (0, 0)
        self._bdv: SearchOut | None = None

    # -- settings ------------------------------------------------------------------------------------------------------

    @staticmethod
    def _search_timing(cmd: flex.Command, max_delay: float) -> tuple[float, float]:
        flex.arity(cmd, 2, 2)
        hold, delay = flex.number(cmd.args[0]), flex.number(cmd.args[1])
        if not (0 <= hold <= 655.35 and 0 <= delay <= max_delay):
            raise flex.FlexError(flex.ERR_PARAMETER, f"hold {hold} delay {delay}")
        return hold, delay

    @handles("LSTM", "BST", "BDT")
    def _cmd_search_timing(self, cmd: flex.Command) -> None:
        """``LSTM``/``BST hold,delay`` (PDF 459, 374) and ``BDT hold,delay`` (PDF 365)."""
        timing = self._search_timing(cmd, 6.5535 if cmd.mnemonic == "BDT" else 65.535)
        if cmd.mnemonic == "LSTM":
            self._lstm = timing
        elif cmd.mnemonic == "BST":
            self._bst = timing
        else:
            self._bdt = timing

    @handles("LSM")
    def _cmd_lsm(self, cmd: flex.Command) -> None:
        """``LSM abort[,post]``: abort 1 off / 2 on; post 1 start / 2 stop / 3 last (PDF 454-455)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if abort not in (1, 2) or post not in (1, 2, 3):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._lsm = (abort, post)

    @handles("BSM")
    def _cmd_bsm(self, cmd: flex.Command) -> None:
        """``BSM mode,abort[,post]``: mode 0 normal / 1 cautious, abort and post as ``LSM`` (PDF 370-372)."""
        flex.arity(cmd, 2, 3)
        mode, abort = flex.integer(cmd.args[0]), flex.integer(cmd.args[1])
        post = flex.integer(cmd.args[2]) if len(cmd.args) > 2 else 1
        if mode not in (0, 1) or abort not in (1, 2) or post not in (1, 2, 3):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._bsm = (mode, abort, post)

    @handles("LSVM", "BSVM")
    def _cmd_search_output(self, cmd: flex.Command) -> None:
        """``LSVM``/``BSVM mode``: 0 ``Data_search`` only, 1 with ``Data_sense`` (PDF 460, 375)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        if cmd.mnemonic == "LSVM":
            self._lsvm = mode
        else:
            self._bsvm = mode

    @handles("LGI", "LGV", "BGI", "BGV")
    def _cmd_search_monitor(self, cmd: flex.Command) -> None:
        """``LGI``/``LGV chnum,mode,range,target`` (PDF 443-444) and ``BGI``/``BGV chnum,mode,condition,range,target``
        (PDF 366-369): the monitor of the linear/binary search; each clears its other quantity's setting."""
        binary = cmd.mnemonic.startswith("B")
        flex.arity(cmd, 5 if binary else 4, 5 if binary else 4)
        quantity = "I" if cmd.mnemonic.endswith("I") else "V"
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {mode}")
        condition = 0.0
        if binary:
            condition = flex.number(cmd.args[2])
            if (mode == 0 and condition <= 0) or (mode == 1 and (condition != int(condition)
                                                                 or not 1 <= condition <= 16)):
                raise flex.FlexError(flex.ERR_PARAMETER, f"condition {condition}")
        rng = flex.integer(cmd.args[-2])
        if quantity == "I" and rng != 0 and abs(rng) not in self._i_codes(channel):
            raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        if quantity == "V" and rng not in flex.V_MEAS_CODES:
            raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        target = flex.number(cmd.args[-1])
        if abs(target) > (flex.SMU_MAX_I if quantity == "I" else flex.SMU_MAX_V):
            raise flex.FlexError(flex.ERR_PARAMETER, f"target {target}")
        monitor = SearchMon(channel, quantity, mode, condition, rng, target)
        if binary:
            self._bgx = monitor
        else:
            self._lgx = monitor

    def _search_out(self, cmd: flex.Command, *, linear: bool) -> SearchOut:
        source = "V" if cmd.mnemonic.endswith("V") else "I"
        flex.arity(cmd, 6 if linear else 5, 6 if linear else 5)
        channel = self._smu(cmd.args[0])
        if source == "V":
            rng = flex.integer(cmd.args[1])
            if rng not in flex.V_RANGE_MAX:
                raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        else:
            rng = self._output_irange(channel, cmd.args[1])
        start, stop = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        peak = max(abs(start), abs(stop))
        if peak > (flex.SMU_MAX_V if source == "V" else flex.SMU_MAX_I):
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} {source}")
        if start == stop:
            raise flex.FlexError(ERR_SEARCH_START_STOP)
        step = None
        if linear:
            step = flex.number(cmd.args[4])
            if step == 0 or (step > 0) != (stop > start):
                raise flex.FlexError(flex.ERR_PARAMETER, f"step {step}")
            if abs(step) < self._resolution(channel, source, rng, peak) * (1 - 1e-9):
                raise flex.FlexError(ERR_SEARCH_STEP, f"step {step}")
            if math.floor(abs(stop - start) / abs(step) + 1e-9) + 1 > LINEAR_MAX_STEPS:
                raise flex.FlexError(flex.ERR_PARAMETER, f"more than {LINEAR_MAX_STEPS} steps")
        comp = flex.number(cmd.args[-1])
        allowed = flex.max_icomp(peak) if source == "V" else max_vcomp(peak)
        if comp == 0 or abs(comp) > allowed:
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"comp {comp}")
        self._check_interlock(peak if source == "V" else abs(comp))
        return SearchOut(channel, source, rng, start, stop, abs(comp), step)

    @handles("LSV", "LSI")
    def _cmd_lsx(self, cmd: flex.Command) -> None:
        """``LSV chnum,range,start,stop,step[,Icomp]`` / ``LSI ...[,Vcomp]`` (PDF 453-454, 459-460); the compliance is
        always sent by this driver (the previous value is not simulated). Clears the other source and ``LSSV``/
        ``LSSI``."""
        self._lsx = self._search_out(cmd, linear=True)
        self._lssx = None

    @handles("BSV", "BSI")
    def _cmd_bsx(self, cmd: flex.Command) -> None:
        """``BSV chnum,range,start,stop[,Icomp]`` / ``BSI ...[,Vcomp]`` (PDF 369, 374-375); clears the other source
        and ``BSSV``/``BSSI``."""
        self._bsx = self._search_out(cmd, linear=False)
        self._bssx = None

    @handles("LSSV", "LSSI", "BSSV", "BSSI")
    def _cmd_search_sync(self, cmd: flex.Command) -> None:
        """``LSSV``/``LSSI``/``BSSV``/``BSSI chnum,polarity,offset[,comp]`` (PDF 372-374, 455-457): after the search
        source of the same output mode (error 270 without one, 273 with the other mode)."""
        flex.arity(cmd, 4, 4)
        source = "V" if cmd.mnemonic.endswith("V") else "I"
        primary = self._bsx if cmd.mnemonic.startswith("B") else self._lsx
        if primary is None:
            raise flex.FlexError(ERR_NO_SEARCH_SOURCE, f"{cmd.mnemonic} before its search source")
        if primary.source != source:
            raise flex.FlexError(ERR_SEARCH_SYNC_MODE)
        channel = self._smu(cmd.args[0])
        polarity = flex.integer(cmd.args[1])
        if polarity not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"polarity {polarity}")
        offset = flex.number(cmd.args[2])
        sign = 1 if polarity == 1 else -1
        peak = max(abs(sign * primary.start + offset), abs(sign * primary.stop + offset))
        if peak > (flex.SMU_MAX_V if source == "V" else flex.SMU_MAX_I):
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} {source}")
        comp = flex.number(cmd.args[3])
        allowed = flex.max_icomp(peak) if source == "V" else max_vcomp(peak)
        if comp == 0 or abs(comp) > allowed:
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"comp {comp}")
        self._check_interlock(peak if source == "V" else abs(comp))
        sync = SearchSync(channel, source, sign, offset, abs(comp))
        if cmd.mnemonic.startswith("B"):
            self._bssx = sync
        else:
            self._lssx = sync

    @handles("BDM")
    def _cmd_bdm(self, cmd: flex.Command) -> None:
        """``BDM interval[,mode]``: interval 0 short / 1 long, mode 0 voltage / 1 current (PDF 364)."""
        flex.arity(cmd, 1, 2)
        interval = flex.integer(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 0
        if interval not in (0, 1) or mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._bdm = (interval, mode)

    @handles("BDV")
    def _cmd_bdv(self, cmd: flex.Command) -> None:
        """``BDV chnum,range,start,stop[,Icomp]`` (PDF 365-366): 0 to +/-100 V, ``|start - stop| >= 10 V``."""
        flex.arity(cmd, 5, 5)
        channel = self._smu(cmd.args[0])
        rng = flex.integer(cmd.args[1])
        if rng not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        start, stop = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        peak = max(abs(start), abs(stop))
        if peak > flex.SMU_MAX_V or abs(stop - start) < BDV_MIN_SPAN_V - 1e-12:
            raise flex.FlexError(flex.ERR_PARAMETER, f"start {start} stop {stop}")
        icomp = flex.number(cmd.args[4])
        if icomp == 0 or abs(icomp) > flex.max_icomp(peak):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Icomp {icomp}")
        self._check_interlock(peak)
        self._bdv = SearchOut(channel, "V", rng, start, stop, abs(icomp))

    # -- helpers -------------------------------------------------------------------------------------------------------

    def _resolution(self, channel: int, source: str, rng: int, peak: float) -> float:
        """Output resolution of a search source: 5e-5 of the range it uses (the minimum covering ``peak``, never
        below a limited-auto range)."""
        if source == "V":
            floor = flex.V_RANGE_MAX.get(rng, 100.0) if rng != 0 else 0.0
            full = next((r for r in V_RANGES if r >= max(peak, floor) - 1e-12), V_RANGES[-1])
        else:
            floor = flex.current_range(rng) if rng != 0 else 0.0
            codes = sorted(self._i_codes(channel)) or [19]
            need = max(peak, floor) * (1 - 1e-9)
            full = next((flex.current_range(c) for c in codes if flex.current_range(c) >= need),
                        flex.current_range(codes[-1]))
        return full * RESOLUTION_FRACTION

    def _forcing(self, channel: int, src: SearchOut, sync: SearchSync | None) -> str | None:
        """What ``channel`` forces during the search (``V``/``I``), ``None`` when its output is off."""
        if channel == src.channel:
            return src.source
        if sync is not None and channel == sync.channel:
            return sync.source
        state = self.state.channels.get(channel)
        if state is None or not state.output_on:
            return None
        return state.mode

    def _monitor_comp(self, mon: SearchMon, src: SearchOut, sync: SearchSync | None) -> float:
        if mon.channel == src.channel:
            return src.comp
        if sync is not None and mon.channel == sync.channel:
            return sync.comp
        state = self.state.channels[mon.channel]
        comp = state.icomp if mon.quantity == "I" else state.vcomp
        return abs(comp) if comp is not None else math.inf

    # -- trigger -------------------------------------------------------------------------------------------------------

    def _start_search(self, mode: int, channels: list[int]) -> None:
        """``XE`` with ``MM 9``, ``14`` or ``15``: check the setup (errors 270-279, 610, 200), evaluate, busy until
        its end."""
        if mode == 9:
            if self._bdv is None:
                raise flex.FlexError(ERR_NO_QUASI_SOURCE)
            measured = channels[0] if channels else self._bdv.channel
            for channel in {self._bdv.channel, measured}:
                if not self.state.channels[channel].output_on:
                    raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
            self._measurement = self._measure_quasi(self._bdv, measured, self._now())
        else:
            linear = mode == 14
            src, sync, mon = (self._lsx, self._lssx, self._lgx) if linear else (self._bsx, self._bssx, self._bgx)
            if src is None:
                raise flex.FlexError(ERR_NO_SEARCH_SOURCE)
            if mon is None:
                raise flex.FlexError(ERR_NO_SEARCH_MONITOR)
            if sync is not None and sync.channel == src.channel:
                raise flex.FlexError(ERR_SEARCH_SYNC_CHANNEL)
            involved = {src.channel, mon.channel, *([sync.channel] if sync is not None else [])}
            for channel in involved:
                if not self.state.channels[channel].output_on:
                    raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
            forcing = self._forcing(mon.channel, src, sync)
            if (mon.quantity == "I") != (forcing == "V"):
                raise flex.FlexError(ERR_SEARCH_MONITOR_SIDE)
            if abs(mon.target) > self._monitor_comp(mon, src, sync) * (1 + 1e-12):
                raise flex.FlexError(ERR_SEARCH_TARGET)
            self._measurement = self._measure_search(mode, src, sync, mon, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    # -- engine --------------------------------------------------------------------------------------------------------

    def _search_levels(self, src: SearchOut, sync: SearchSync | None, value: float, levels0: dict[int, float],
                       currents0: dict[int, tuple[float, float]]) -> tuple[dict[int, float], dict[int, float],
                                                                          dict[int, tuple[float, float]]]:
        """Voltage levels, their compliances and the current sources with the search source at ``value``."""
        levels, forced = dict(levels0), dict(currents0)
        icomps = {ch: self._icomp(ch) for ch in levels}
        outputs = [(src.channel, src.source, value, src.comp)]
        if sync is not None:
            outputs.append((sync.channel, sync.source, sync.value(value), sync.comp))
        for channel, source, level, comp in outputs:
            if source == "V":
                levels[channel], icomps[channel] = level, comp
                forced.pop(channel, None)
            else:
                forced[channel] = (level, comp)
                levels.pop(channel, None)
                icomps.pop(channel, None)
        return levels, icomps, forced

    def _evaluate(self, src: SearchOut, sync: SearchSync | None, value: float, levels0: dict[int, float],
                  currents0: dict[int, tuple[float, float]]) -> tuple[dict[int, float], dict[int, float], set[int]]:
        """Solve the outputs with the search source at ``value``; when the source is limited, its programmed level is
        committed first (module docstring: abrupt breakdown) and the outputs solved again."""
        levels, icomps, forced = self._search_levels(src, sync, value, levels0, currents0)
        applied, currents, clamped = self.solve(levels, icomps, forced)
        if self.circuit.has_state:
            if src.channel in clamped and src.source == "V":
                self.circuit.commit({**applied, src.channel: value})
                applied, currents, clamped = self.solve(levels, icomps, forced)
            self.circuit.commit(applied)
        return applied, currents, clamped

    def _search_point(self, src: SearchOut, sync: SearchSync | None, mon: SearchMon, value: float, index: int,
                      levels0: dict[int, float], currents0: dict[int, tuple[float, float]],
                      rng: random.Random) -> SearchPoint:
        """Measure the monitor with the source at ``value`` (point ``index`` for the step faults)."""
        applied, currents, clamped = self._evaluate(src, sync, value, levels0, currents0)
        faulted = {canonical_channel(ch) for ch in self.faults.compliance_channels(index)}
        limited = clamped | faulted
        involved = {src.channel, mon.channel, *([sync.channel] if sync is not None else []), *levels0, *currents0}
        statuses = {ch: "C" if ch in limited else ("T" if limited else "N") for ch in involved}
        if self.faults.oscillating(index):
            statuses = {ch: worst_status([s, "X"]) for ch, s in statuses.items()}
        if mon.quantity == "I":
            reading = currents.get(mon.channel, 0.0)
            if mon.channel in faulted:
                comp = self._monitor_comp(mon, src, sync)
                reading = math.copysign(comp, reading if reading != 0 else (value or 1.0))
            else:
                reading += self._noise(mon.channel, reading, rng)
        else:
            reading = applied.get(mon.channel, 0.0)
        return SearchPoint(value, reading, statuses[mon.channel], statuses)

    @staticmethod
    def _satisfied(mon: SearchMon, reading: float, *, linear: bool) -> bool:
        if linear:
            return reading >= mon.target if mon.mode == 1 else reading <= mon.target
        return mon.mode == 0 and abs(reading - mon.target) <= mon.condition * (1 + 1e-12)

    @staticmethod
    def _brackets(a: float, b: float, target: float) -> bool:
        return (a - target) * (b - target) <= 0

    def _measure_search(self, mode: int, src: SearchOut, sync: SearchSync | None, mon: SearchMon,
                        t0: float) -> Measurement:
        linear = mode == 14
        factor = self.faults.slow_factor()
        hold, delay = self._lstm if linear else self._bst
        abort_on = (self._lsm[0] if linear else self._bsm[1]) == 2
        post = self._lsm[1] if linear else self._bsm[2]
        sense = (self._lsvm if linear else self._bsvm) == 1
        per_point = delay + self.integration_time(mon.channel)
        levels0, currents0 = self._on_levels(), self._on_currents()
        for channel in [src.channel, *([sync.channel] if sync is not None else [])]:
            levels0.pop(channel, None)
            currents0.pop(channel, None)
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        points: list[SearchPoint] = []
        status = "G"
        zero_at: float | None = None
        interlock = False

        def measure(value: float) -> SearchPoint | None:
            nonlocal interlock
            index = len(points)
            if self.faults.interlock_opens_at(index):
                self._interlock_open = True
            levels, _, forced = self._search_levels(src, sync, value, levels0, currents0)
            potentials = {**levels, **{ch: comp for ch, (_, comp) in forced.items()}}
            if self.interlock_open() and self._high_voltage(potentials):
                self._queue_error(flex.ERR_INTERLOCK)  # all outputs to 0 V, error 202 (PG PDF 577)
                interlock = True
                return None
            point = self._search_point(src, sync, mon, value, index, levels0, currents0, rng)
            points.append(point)
            return point

        def stop_here(point: SearchPoint) -> str | None:
            if self._satisfied(mon, point.reading, linear=linear):
                return "N"
            if abort_on and any(s in ABORT_STATUSES for s in point.statuses.values()):
                return "S"
            return None

        if linear:
            for value in src.values():
                point = measure(value)
                if point is None:
                    break
                ended = stop_here(point)
                if ended is not None:
                    status = ended
                    break
        else:
            status = self._binary(src, mon, measure, stop_here)
        result = self._search_result(points, status, mon, linear=linear)
        end = t0 + factor * (hold + max(len(points), 1) * per_point)
        if interlock:
            zero_at = end
            status = "S"
        texts = self._search_texts(src, mon, result, status, sense, interlock)
        if self.circuit.has_state:
            device_states.append(self.circuit.export_state())
        self._sync_devices()
        measurement = Measurement(t0, end, [end], [texts], None, None, zero_at, device_states)
        if not interlock:  # after an interlock abort every output is at 0 V (zero_at)
            last = result.value if result is not None else src.start
            measurement.on_end = self._search_end_action(src, sync, post, last, status == "S")
        return measurement

    def _binary(self, src: SearchOut, mon: SearchMon, measure: Callable[[float], SearchPoint | None],
                stop_here: Callable[[SearchPoint], str | None]) -> str:
        """The binary search sequence (module docstring); returns the ``Data_search`` status."""
        normal = self._bsm[0] == 0
        resolution = self._resolution(src.channel, src.source, src.out_range, max(abs(src.start), abs(src.stop)))
        first = measure(src.start)
        if first is None:
            return "S"
        ended = stop_here(first)
        if ended is not None:
            return ended
        low: tuple[float, float] = (src.start, first.reading)
        high: tuple[float, float | None] = (src.stop, None)
        changes = 0
        if normal:
            second = measure(src.stop)
            if second is None:
                return "S"
            changes = 1
            ended = stop_here(second)
            if ended is not None:
                return ended
            if not self._brackets(first.reading, second.reading, mon.target):
                return "G"
            high = (src.stop, second.reading)
        while True:
            change = abs(high[0] - low[0]) / 2
            if change < resolution:
                return "G" if mon.mode == 0 else "N"
            value = (low[0] + high[0]) / 2
            point = measure(value)
            if point is None:
                return "S"
            changes += 1
            ended = stop_here(point)
            if ended is not None:
                return ended
            if mon.mode == 1 and changes >= int(mon.condition):
                return "N"
            if self._brackets(low[1], point.reading, mon.target):
                high = (value, point.reading)
            else:
                low = (value, point.reading)

    @staticmethod
    def _search_result(points: list[SearchPoint], status: str, mon: SearchMon, *, linear: bool) -> SearchPoint | None:
        """The returned point: the last one (found, stopped, not found), the closest to the target for a binary
        repeat-mode search."""
        if not points:
            return None
        if not linear and status == "N" and mon.mode == 1:
            return min(points, key=lambda p: abs(p.reading - mon.target))
        return points[-1]

    def _search_texts(self, src: SearchOut, mon: SearchMon, result: SearchPoint | None, status: str, sense: bool,
                      interlock: bool) -> list[str]:
        if result is None or interlock:  # interlock abort: dummy data (status V, 199.999E+99; PDF 53)
            texts = [Element("V", src.channel, src.source, 0.0).text()]
            if sense:
                texts.append(Element("V", mon.channel, mon.quantity, 0.0).text())
            return texts
        texts = [Element(status, src.channel, src.source, result.value).text()]
        if sense:
            texts.append(Element(result.status, mon.channel, mon.quantity, result.reading).text())
        if self.faults.garbage_at(0):
            texts[0] = GARBAGE_ELEMENT
        return texts

    def _search_end_action(self, src: SearchOut, sync: SearchSync | None, post: int, last: float,
                           stopped: bool) -> Callable[[bool], None]:
        """After the search the sources force start (post 1, an automatic abort or ``AB``), stop (2) or the last
        value (3) (PDF 134, 370, 455)."""

        def apply(aborted: bool) -> None:
            value = src.start if aborted or stopped or post == 1 else (src.stop if post == 2 else last)
            for channel, source, level, comp in [(src.channel, src.source, value, src.comp),
                                                 *([(sync.channel, sync.source, sync.value(value), sync.comp)]
                                                   if sync is not None else [])]:
                state = self.state.channels[channel]
                if state.output_on:
                    force_source(state, source, level, comp)  # type: ignore[arg-type]

        return apply

    # -- quasi-pulsed spot ---------------------------------------------------------------------------------------------

    def _measure_quasi(self, src: SearchOut, measured: int, t0: float) -> Measurement:
        factor = self.faults.slow_factor()
        hold, delay = self._bdt
        interval, mode = self._bdm
        levels0, currents0 = self._on_levels(), self._on_currents()
        levels0.pop(src.channel, None)
        currents0.pop(src.channel, None)
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []

        def clamped_at(value: float) -> bool:
            levels, icomps, forced = self._search_levels(src, None, value, levels0, currents0)
            return src.channel in self.solve(levels, icomps, forced)[2]

        detected: float | None = None
        interlock = False
        if self.faults.interlock_opens_at(0):
            self._interlock_open = True
        if self.interlock_open() and self._high_voltage({**levels0, src.channel: max(src.start, src.stop, key=abs)}):
            self._queue_error(flex.ERR_INTERLOCK)
            interlock = True
        else:
            if self.circuit.has_state:
                self.circuit.commit(self._search_levels(src, None, src.start, levels0, currents0)[0])
            count = max(2, math.ceil(abs(src.stop - src.start) / QUASI_GRID_V))
            previous = src.start
            for k in range(1, count + 1):
                value = src.start + (src.stop - src.start) * k / count
                if clamped_at(value):
                    low, high = previous, value
                    for _ in range(80):
                        mid = 0.5 * (low + high)
                        if clamped_at(mid):
                            high = mid
                        else:
                            low = mid
                        if abs(high - low) < 1e-9:
                            break
                    detected = high
                    break
                previous = value
        x_value = detected if detected is not None else src.stop
        forced_compliance = canonical_channel(src.channel) in {canonical_channel(c)
                                                               for c in self.faults.compliance_channels(0)}
        if detected is None and forced_compliance:
            detected = x_value
        if interlock:
            status, reading = "V", 0.0
        else:
            if detected is None:
                status = "N"
            else:
                status = "C" if abs(x_value - src.start) >= BDV_MIN_SPAN_V - 1e-9 else "S"
            applied, currents, _ = self._evaluate(src, None, x_value, levels0, currents0)
            if measured != src.channel and detected is not None and status != "S":
                status = "T"
            if mode == 0:
                reading = x_value if measured == src.channel else applied.get(measured, 0.0)
            elif measured == src.channel and detected is not None:
                reading = math.copysign(src.comp, x_value if x_value != 0 else 1.0)
            else:
                reading = currents.get(measured, 0.0)
                reading += self._noise(measured, reading, rng)
            if self.faults.oscillating(0):
                status = worst_status([status, "X"]) if status in "NTC" else status
        ramp = abs(x_value - src.start) / QUASI_SLEW_V_PER_S[interval]
        end = t0 + factor * (hold + ramp + delay + self.integration_time(measured))
        texts = [Element(status, measured, "V" if mode == 0 else "I", reading).text()]
        if self.faults.garbage_at(0):
            texts[0] = GARBAGE_ELEMENT
        if self.circuit.has_state:
            device_states.append(self.circuit.export_state())
        self._sync_devices()
        measurement = Measurement(t0, end, [end], [texts], None, None, end if interlock else None, device_states)
        if not interlock:
            measurement.on_end = self._search_end_action(src, None, 1, src.start, True)
        return measurement


__all__ = ["SEARCH_MODES", "SearchUnit"]
