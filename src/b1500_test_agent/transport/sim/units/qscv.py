"""SMU quasi-static C-V unit of the simulator (``MM 13``): ``QSV``, ``QST``, ``QSM``, ``QSL``, ``QSO``, ``QSC``,
``QSR``, ``QSZ``, ``*LRN? 49`` and the QSCV engine (blueprint v2 4.1, kind ``smu_qscv``, WP8.5).

``QscvUnit`` is a mixin of ``SimInstrument``. ``SmuUnit._cmd_mm`` accepts ``MM 13[,ch]`` and ``SmuUnit._cmd_xe`` hands
its trigger to ``_start_qscv``. Manual references (Programming Guide Ed. 15): operation p115-117 (2-27 to 2-29),
example Table 3-17 p241-245 (3-61 to 3-65), data p49 (1-29); ``QSC``/``QSL`` p493 (4-175), ``QSM`` p494 (4-176),
``QSO`` p495 (4-177), ``QSR``/``QST`` p496-497 (4-178 to 4-179), ``QSV`` p497-499 (4-179 to 4-181), ``QSZ`` p499-500
(4-181 to 4-182), ``*LRN? 49`` p450 (4-132); errors 240-247 p580-581 (5-8 to 5-9).

Engine (evaluated at ``XE`` in virtual time, the devices evolving through every interval with ``Circuit.advance``):
after the hold at the first step's lower level, each measured step ``V_N`` (start and stop excluded; the double sweep
measures the same steps back) forces ``V_N - d Vq`` (``d`` the sweep direction, ``Vq = cvoltage/2``), waits delay1,
integrates the leakage ``IL0`` over linteg (the step to the lower level settles first), ramps linearly to ``V_N + d
Vq`` over cinteg (``RAMP_SUBSTEPS`` intervals, trapezoid rule: the charge current ``I`` is the displacement charge plus
the mean DC current, ``Vavg`` the time average of the applied voltage), integrates ``IL`` over linteg and waits
delay2. ``|step| = cvoltage`` joins the transitions (delay2 0, ``V0``/``IL0`` of the previous step reused; PG
p116). ``C = (I - Leak) cinteg / (V - V0)`` with ``Leak = IL0 + (IL - IL0)(Vavg - V0)/(V - V0)`` (``QSC 0``) or ``IL +
tau (IL0 - IL)/(2 cinteg)`` with ``tau`` = cinteg, the ramp time (``QSC 1``); without compensation ``Leak`` is not
subtracted (it is still the leakage datum with ``QSL 1,x``); ``QSL 0,0`` measures no leakage at all. ``QSZ 1``
subtracts the offset the last ``QSZ 2`` measured on the measurement channel (``state.qscv_offsets``, 0 when none).
The measured current includes the path's guard capacitance ``QSCV_STRAY_F`` (``C_stray (V - V0) / cinteg``), which
``QSZ 2`` measures (the terminals open at the device end: the DUT takes no part). Current noise per integrated reading
``m x hypot(floor, rel x I)`` with the scenario's noise and ``m`` from the integration time (``core``'s
multipliers); a reading above ``OVERRANGE`` x the ``QSR`` range is status ``V``; the source's compliance (a DC solve,
or a mean charge current above Icomp) is ``C`` (``T`` on the other channel). With ``QSM 2`` a ``C``/``T``/``V``/``X``
step stops the sweep: the rest is dummy data (``199.999E+99``, status ``V``), error 242 is queued and the source
returns to start. After a normal end the source forces start or stop (``QSM`` post).

Simulator conventions (TODO(verify)[L6.A6, L6.A8]): the transition is a linear ramp over cinteg; the
guard capacitance of the path is ``QSCV_STRAY_F``; the offset measurement takes ``linteg + cinteg + linteg`` and raises
error 245 when the offset current ``C_stray cvoltage / cinteg`` exceeds the range; ``*RST`` and a device clear clear
the stored offsets; the smart operation (``QSO 1``) is not simulated (error 100 at ``XE``; no kind enables it); a
measurement channel other than the source measures its own current with the same formula (no kind does that).
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
from b1500_test_agent.transport.sim.units.base import Measurement, Unsupported, handles, learns
from b1500_test_agent.transport.sim.units.smu import OVERRANGE, force_source

QSCV_MODE = 13
"""``MM 13[,ch]``: quasi-static C-V (Table 4-28, PDF 471)."""

QSCV_RANGES: dict[int, float] = {-9: 1e-11, -10: 1e-10, -11: 1e-9, -12: 1e-8, -13: 1e-7, -14: 1e-6}
"""``QSR`` code -> full scale (A) (PG p496 (4-178))."""

QSCV_MAX_STEPS = 1001
QSCV_MAX_CVOLTAGE_V = 10.0
CINTEG_N = (1, 20000)
LINTEG_N = (1, 100)
"""``QSV`` step count, cvoltage, ``QST`` integration multiples of the line period (PG p496-498)."""

QSCV_STRAY_F = 0.25e-12
"""Guard capacitance of the SMU path that a QSCV measurement sees (simulator convention, TODO(verify)[L6.A6]: the
``qscv_offset`` record): ``QSZ 2`` measures it, ``QSZ 1`` removes it."""

RAMP_SUBSTEPS = 8
"""Sub-intervals of the linear transition ramp over cinteg."""

RESOLUTION_FRACTION = 5e-5
V_RANGES = (0.5, 2.0, 5.0, 20.0, 40.0, 100.0)
"""Output resolution of an SMU voltage range as a fraction of its full scale and the MP/HRSMU ranges (Tables 4-6,
4-7, PDF 341-342): cvoltage must be at least twice the resolution (PG p498)."""

ABORT_STATUSES = frozenset("CTVX")

ERR_NO_QSV = 240
ERR_QSR_RANGE = 241
ERR_QSCV_ABORTED = 242
ERR_QSZ_BEFORE_MM = 243
ERR_QSZ_RANGE = 245
ERR_QSV_MODE = 246
ERR_QSO_CHANNEL = 247


@dataclass(frozen=True)
class QsvSource:
    """The ``QSV`` sweep source (``mode`` 1 single, 3 double; ``cvoltage`` as sent, reduced to the step at ``XE``)."""

    channel: int
    mode: int
    out_range: int
    start: float
    stop: float
    cvoltage: float
    steps: int
    comp: float

    @property
    def step(self) -> float:
        """Signed sweep step voltage ``(stop - start) / (steps + 1)``."""
        return (self.stop - self.start) / (self.steps + 1)

    @property
    def one_point(self) -> bool:
        """``step = 1`` and ``|stop - start| <= 10 V``: one capacitance measurement between start and stop, cvoltage
        ignored (PG p498)."""
        return self.steps == 1 and abs(self.stop - self.start) <= 10.0

    def plan(self) -> list[tuple[float, float, float]]:
        """``(V_N, d, Vq)`` per measured step in order (module docstring)."""
        if self.one_point:
            mid, half = 0.5 * (self.start + self.stop), 0.5 * abs(self.stop - self.start)
            return [(mid, math.copysign(1.0, self.stop - self.start), half)]
        d = math.copysign(1.0, self.stop - self.start)
        vq = 0.5 * min(self.cvoltage, abs(self.step))
        forward = [(self.start + self.step * k, d, vq) for k in range(1, self.steps + 1)]
        if self.mode == 3:
            return forward + [(v, -d, q) for v, _, q in reversed(forward)]
        return forward


@dataclass
class _Reading:
    """One measured QSCV step before formatting."""

    voltage: float
    capacitance: float
    leakage: float
    status: str
    leak_status: str
    stamp: float


class QscvUnit:
    """QSCV handlers and engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_qscv_settings(self) -> None:
        """QSCV setup to its initial settings (PG Table 2-13, PDF 180; command pages)."""
        plc5 = 5.0 / flex.LINE_FREQUENCY_HZ
        self._qsv: QsvSource | None = None
        self._qst: tuple[float, float, float, float, float] = (plc5, plc5, 0.0, 0.0, 0.0)
        self._qsm: tuple[int, int] = (1, 1)
        self._qsl: tuple[int, int] = (0, 0)
        self._qso: tuple[int, int | None, float | None] = (0, None, None)
        self._qsc = 0
        self._qsr = -11
        self._qsz = 0

    def _reset_qscv_state(self) -> None:
        """Power-on, ``*RST`` and device clear: no stored offset (simulator convention)."""
        self.state.qscv_offsets.clear()

    # -- settings ------------------------------------------------------------------------------------------------------

    @handles("QSV")
    def _cmd_qsv(self, cmd: flex.Command) -> None:
        """``QSV chnum,mode,vrange,start,stop,cvoltage,step[,Icomp]`` (PG p497-499): error 246 for a mode other than
        1/3; cvoltage above 0, at most 10 V and at least twice the output resolution; step 1-1001; the compliance is
        always sent by this driver (without it the channel's present compliance is used)."""
        flex.arity(cmd, 7, 8)
        channel = self._smu(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (1, 3):
            raise flex.FlexError(ERR_QSV_MODE, f"mode {mode}")
        rng = flex.integer(cmd.args[2])
        if rng not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        start, stop = flex.number(cmd.args[3]), flex.number(cmd.args[4])
        peak = max(abs(start), abs(stop))
        if peak > flex.SMU_MAX_V or start == stop:
            raise flex.FlexError(flex.ERR_PARAMETER, f"start {start} stop {stop}")
        cvoltage = flex.number(cmd.args[5])
        floor = flex.V_RANGE_MAX.get(rng, 100.0) if rng != 0 else 0.0
        full = next((r for r in V_RANGES if r >= max(peak, floor) - 1e-12), V_RANGES[-1])
        if not 2.0 * RESOLUTION_FRACTION * full * (1 - 1e-9) <= cvoltage <= QSCV_MAX_CVOLTAGE_V:
            raise flex.FlexError(flex.ERR_PARAMETER, f"cvoltage {cvoltage}")
        steps = flex.integer(cmd.args[6])
        if not 1 <= steps <= QSCV_MAX_STEPS:
            raise flex.FlexError(flex.ERR_PARAMETER, f"step {steps}")
        if len(cmd.args) > 7:
            comp = flex.number(cmd.args[7])
        else:
            present = self.state.channels[channel].icomp
            comp = present if present is not None else 1e-4
        if comp == 0 or abs(comp) > flex.max_icomp(peak):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Icomp {comp}")
        self._check_interlock(peak)
        self._qsv = QsvSource(channel, mode, rng, start, stop, cvoltage, steps, abs(comp))

    @handles("QST")
    def _cmd_qst(self, cmd: flex.Command) -> None:
        """``QST cinteg,linteg,hold,delay1[,delay2]`` (PG p496-497): integration times rounded to ``n / line
        frequency`` (cinteg n 1-20000, linteg n 1-100); hold 0-655.35 s, delays 0-65.535 s."""
        flex.arity(cmd, 4, 5)
        cinteg, linteg = flex.number(cmd.args[0]), flex.number(cmd.args[1])
        hold, delay1 = flex.number(cmd.args[2]), flex.number(cmd.args[3])
        delay2 = flex.number(cmd.args[4]) if len(cmd.args) > 4 else 0.0
        line = flex.LINE_FREQUENCY_HZ
        rounded = []
        for value, (low, high) in ((cinteg, CINTEG_N), (linteg, LINTEG_N)):
            n = math.floor(value * line + 0.5)
            if not low <= n <= high:
                raise flex.FlexError(flex.ERR_PARAMETER, f"integration time {value}")
            rounded.append(n / line)
        if not (0 <= hold <= 655.35 and 0 <= delay1 <= 65.535 and 0 <= delay2 <= 65.535):
            raise flex.FlexError(flex.ERR_PARAMETER, f"hold {hold} delays {delay1}, {delay2}")
        self._qst = (rounded[0], rounded[1], hold, delay1, delay2)

    @handles("QSM")
    def _cmd_qsm(self, cmd: flex.Command) -> None:
        """``QSM abort[,post]``: abort 1 off / 2 on, post 1 start / 2 stop (PG p494-495)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if abort not in (1, 2) or post not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._qsm = (abort, post)

    @handles("QSL")
    def _cmd_qsl(self, cmd: flex.Command) -> None:
        """``QSL data,compen`` (PG p493-494): leakage data output and compensation, each 0 or 1."""
        flex.arity(cmd, 2, 2)
        data, compen = flex.integer(cmd.args[0]), flex.integer(cmd.args[1])
        if data not in (0, 1) or compen not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._qsl = (data, compen)

    @handles("QSO")
    def _cmd_qso(self, cmd: flex.Command) -> None:
        """``QSO mode[,chnum[,Vcomp]]`` (PG p495): needs ``QSC 0``; mode 0 takes no further parameter, mode 1 the
        dedicated SMU (error 247 without one)."""
        flex.arity(cmd, 1, 3)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1) or self._qsc != 0:
            raise flex.FlexError(flex.ERR_PARAMETER, f"QSO {mode} with QSC {self._qsc}")
        if mode == 0:
            if len(cmd.args) > 1:
                raise flex.FlexError(flex.ERR_PARAMETER, "QSO 0 takes no channel")
            self._qso = (0, None, None)
            return
        if len(cmd.args) < 2:
            raise flex.FlexError(ERR_QSO_CHANNEL)
        channel = self._smu(cmd.args[1])
        vcomp = flex.number(cmd.args[2]) if len(cmd.args) > 2 else None
        self._qso = (1, channel, vcomp)

    @handles("QSC")
    def _cmd_qsc(self, cmd: flex.Command) -> None:
        """``QSC mode``: 0 normal, 1 4155C/4156C compatible (PG p493)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._qsc = mode

    @handles("QSR")
    def _cmd_qsr(self, cmd: flex.Command) -> None:
        """``QSR range``: -9 (10 pA) to -14 (1 uA) (PG p496; error 241)."""
        flex.arity(cmd, 1, 1)
        code = flex.integer(cmd.args[0])
        if code not in QSCV_RANGES:
            raise flex.FlexError(ERR_QSR_RANGE, f"QSR {code}")
        self._qsr = code

    @handles("QSZ")
    def _cmd_qsz(self, cmd: flex.Command) -> None:
        """``QSZ mode`` (PG p499-500): 0/1 offset cancel off/on; 2 measures the offset (terminals open) and returns one
        datum. ``MM 13`` first (error 243); mode 2 needs the ``QSV`` setup (240) and the channels on (200)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        if self._mm is None or self._mm[0] != QSCV_MODE:
            raise flex.FlexError(ERR_QSZ_BEFORE_MM)
        if mode != 2:
            self._qsz = mode
            return
        src, measured = self._qscv_channels(self._mm[1])
        self._measurement = self._measure_qscv_offset(src, measured, self._now())
        self._busy_until = self._measurement.end

    @learns(49)
    def _lrn_qscv(self, kind: int) -> str:
        """``*LRN? 49``: ``QSM``, ``QSL``, ``QSZ``, ``QSO``, ``QSC``, ``QST``, ``QSR`` and (when set) ``QSV`` (PG p450
        (4-132))."""
        cinteg, linteg, hold, delay1, delay2 = self._qst
        mode, ch, vcomp = self._qso
        qso = f"QSO{mode}" + (f",{ch}" if ch is not None else "") + (f",{vcomp:g}" if vcomp is not None else "")
        parts = [f"QSM{self._qsm[0]},{self._qsm[1]}", f"QSL{self._qsl[0]},{self._qsl[1]}", f"QSZ{self._qsz}", qso,
                 f"QSC{self._qsc}", f"QST{cinteg:g},{linteg:g},{hold:g},{delay1:g},{delay2:g}", f"QSR{self._qsr}"]
        src = self._qsv
        if src is not None:
            parts.append(f"QSV{src.channel},{src.mode},{src.out_range},{src.start:g},{src.stop:g},{src.cvoltage:g},"
                         f"{src.steps},{src.comp:g}")
        return ";".join(parts)

    # -- trigger -------------------------------------------------------------------------------------------------------

    def _qscv_channels(self, channels: list[int]) -> tuple[QsvSource, int]:
        src = self._qsv
        if src is None:
            raise flex.FlexError(ERR_NO_QSV)
        measured = channels[0] if channels else src.channel
        for channel in {src.channel, measured}:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        code = abs(self._qsr)
        if code not in self._i_codes(measured):
            raise flex.FlexError(flex.ERR_RANGE, f"QSR {self._qsr} on {self._channel_type(measured)}")
        return src, measured

    def _start_qscv(self, channels: list[int]) -> None:
        """``XE`` with ``MM 13``: check the setup (errors 240, 200, 124, 247), evaluate, busy until its end."""
        src, measured = self._qscv_channels(channels)
        mode, dedicated, _ = self._qso
        if mode == 1:
            if dedicated is None or dedicated in (src.channel, measured):
                raise flex.FlexError(ERR_QSO_CHANNEL)
            raise Unsupported("QSO 1 (QSCV smart operation) is not simulated")
        self._measurement = self._measure_qscv(src, measured, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    # -- engine --------------------------------------------------------------------------------------------------------

    def _qscv_multiplier(self, seconds: float) -> float:
        plcs = seconds * flex.LINE_FREQUENCY_HZ
        return 3.0 if plcs < 0.25 else (1.0 if plcs < 4.0 else 0.3)

    def _qscv_noise(self, channel: int, current: float, seconds: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = self._qscv_multiplier(seconds) * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0

    def _qscv_advance(self, dt: float, applied: dict[int, float]) -> dict[int, float]:
        """Hold ``applied`` for ``dt`` seconds (devices evolve; the mean displacement current is included) and return
        each SMU's current; MFCMU sides routed to an SMU through the SCUU count as that SMU (``_route_sides``) and an
        SMU on its ASU's AUX input carries nothing."""
        cut = [ch for ch in applied if self._asu_on_aux(ch)]
        connected = {ch: v for ch, v in applied.items() if ch not in cut}
        sides, alias = self._route_sides(connected)
        currents = self.circuit.advance(max(dt, 0.0), {**connected, **sides})
        for side, smu in alias.items():
            current = currents.pop(side, 0.0)
            if smu in currents:
                currents[smu] += current
        out = {node: float(value) for node, value in currents.items() if isinstance(node, int)}
        return {**out, **{ch: 0.0 for ch in cut}}

    def _measure_qscv(self, src: QsvSource, measured: int, t0: float) -> Measurement:
        factor = self.faults.slow_factor()
        cinteg, linteg, hold, delay1, delay2 = self._qst
        abort_on, post = self._qsm[0] == 2, self._qsm[1]
        data_on, compen = self._qsl[0] == 1, self._qsl[1] == 1
        leak_on = data_on or compen
        normal = self._qsc == 0
        range_a = QSCV_RANGES[self._qsr]
        offset = self.state.qscv_offsets.get(measured, 0.0) if self._qsz == 1 else 0.0
        plan = src.plan()
        joined = not src.one_point and math.isclose(2.0 * plan[0][2], abs(src.step), rel_tol=1e-9)
        levels0, currents0 = self._on_levels(), self._on_currents()
        levels0.pop(src.channel, None)
        currents0.pop(src.channel, None)
        icomps = {ch: self._icomp(ch) for ch in levels0}
        icomps[src.channel] = src.comp
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        clock = 0.0  # virtual seconds since XE (before the slow factor)

        def apply(v: float) -> tuple[dict[int, float], set[int]]:
            applied, _, clamped = self.solve({**levels0, src.channel: v}, icomps, currents0)
            return applied, clamped

        def hold_at(v: float, seconds: float, *, settle: bool = False) -> tuple[dict[int, float], dict[int, float],
                                                                                 set[int]]:
            """Hold the source at ``v`` for ``seconds``; ``settle``: the step to ``v`` charges the device first (a
            zero-length interval: the charging spike settles before the integration, as delay1 lets it)."""
            nonlocal clock
            applied, clamped = apply(v)
            if settle:
                self._qscv_advance(0.0, applied)
            currents = self._qscv_advance(seconds, applied)
            clock += seconds
            return applied, currents, clamped

        readings: list[_Reading | None] = []
        step_ends: list[float] = []
        aborted = interlock = False
        previous: tuple[float, float] | None = None  # (V, IL) of the last step, reused by joined transitions
        last_d = plan[0][1]
        for index, (vn, d, vq) in enumerate(plan):
            if aborted:
                readings.append(None)
                step_ends.append(t0 + factor * clock)
                continue
            v_lo, v_hi = vn - d * vq, vn + d * vq
            if self.faults.interlock_opens_at(index):
                self._interlock_open = True
            if self.interlock_open() and self._high_voltage({**levels0, src.channel: max(v_lo, v_hi, key=abs)}):
                self._interlock_trip()  # all outputs to 0 V, error 202 (PG PDF 577)
                interlock = aborted = True
                readings.append(None)
                step_ends.append(t0 + factor * clock)
                continue
            limited: set[int] = set()
            if index == 0 and hold > 0:
                hold_at(v_lo, hold, settle=True)
            reuse = joined and previous is not None and d == last_d
            if delay1 > 0:
                limited |= hold_at(v_lo, delay1, settle=True)[2]
            if reuse:
                assert previous is not None
                v0, il0 = previous
            else:
                applied, currents, clamped = hold_at(v_lo, linteg if leak_on else 0.0, settle=True)
                limited |= clamped
                v0 = applied.get(src.channel, v_lo)
                il0 = currents.get(measured, 0.0) + (self._qscv_noise(measured, currents.get(measured, 0.0), linteg,
                                                                      rng) if leak_on else 0.0)
            stamp = t0 + factor * clock - self._timer_zero
            charge = 0.0
            volts: list[float] = []
            dt = cinteg / RAMP_SUBSTEPS
            previous_v = v0
            previous_dc = self._current(apply(v_lo)[0]).get(measured, 0.0)
            for j in range(1, RAMP_SUBSTEPS + 1):
                applied, currents, clamped = hold_at(v_lo + (v_hi - v_lo) * j / RAMP_SUBSTEPS, dt)
                limited |= clamped
                dc_now = self._current(applied).get(measured, 0.0)
                # trapezoid: the interval's displacement charge plus the mean of the DC current at its two ends
                charge += (currents.get(measured, 0.0) - 0.5 * (dc_now - previous_dc)) * dt
                now_v = applied.get(src.channel, v_hi)
                volts.append(0.5 * (previous_v + now_v))
                previous_v, previous_dc = now_v, dc_now
            v_end = previous_v
            current = charge / cinteg + QSCV_STRAY_F * (v_end - v0) / cinteg
            current += self._qscv_noise(measured, current, cinteg, rng)
            if leak_on:
                applied, currents, clamped = hold_at(v_hi, linteg)
                limited |= clamped
                v_end = applied.get(src.channel, v_end)
                il = currents.get(measured, 0.0)
                il += self._qscv_noise(measured, il, linteg, rng)
            else:
                il = il0 = 0.0
            if delay2 > 0 and not joined:
                hold_at(v_hi, delay2)
            vavg = sum(volts) / len(volts)
            span = v_end - v0
            if span == 0:
                leak = il
            elif normal:
                leak = il0 + (il - il0) * (vavg - v0) / span
            else:
                leak = il + cinteg * (il0 - il) / (2.0 * cinteg)
            capacitance = ((current - (leak if compen else 0.0)) * cinteg / span if span != 0 else 0.0) - offset
            faulted = {canonical_channel(ch) for ch in self.faults.compliance_channels(index)}
            if abs(current) > src.comp * (1 + 1e-12) and measured == src.channel:
                faulted.add(src.channel)
            limited |= faulted
            status = "C" if measured in limited else ("T" if limited else "N")
            leak_status = status
            if abs(current) > OVERRANGE * range_a:
                status = worst_status([status, "V"])
            if leak_on and max(abs(il0), abs(il)) > OVERRANGE * range_a:
                leak_status = worst_status([leak_status, "V"])
            if self.faults.oscillating(index):
                status, leak_status = worst_status([status, "X"]), worst_status([leak_status, "X"])
            readings.append(_Reading(vn, capacitance, leak, status, leak_status, stamp))
            step_ends.append(t0 + factor * clock)
            if self.circuit.has_state:
                device_states.append(self.circuit.export_state())
            previous, last_d = (v_end, il), d
            if abort_on and (status in ABORT_STATUSES or (leak_on and leak_status in ABORT_STATUSES)):
                aborted = True
                self._queue_error(ERR_QSCV_ABORTED)
        blocks = [self._qscv_block(src, measured, reading, plan[k][0], k == len(plan) - 1, k, data_on)
                  for k, reading in enumerate(readings)]
        self._sync_devices()
        end = step_ends[-1] if step_ends else t0
        measurement = Measurement(t0, end, step_ends, blocks, None, None, end if interlock else None, device_states)
        if not interlock:
            measurement.on_end = self._qscv_end_action(src, post, aborted)
        return measurement

    def _qscv_block(self, src: QsvSource, measured: int, reading: _Reading | None, voltage: float, is_last: bool,
                    index: int, data_on: bool) -> list[str]:
        """One step's elements: ``[Time,] [DataL,] DataC [,Source_data]`` (PG p49; dummy data after an abort)."""
        texts: list[str] = []
        if self._tsc:
            texts.append(Element("N", measured, "T", reading.stamp if reading is not None else 0.0).text())
        if reading is None:
            if data_on:
                texts.append(Element("V", measured, "I", 0.0).text())
            texts.append(Element("V", measured, "C", 0.0).text())
        else:
            if data_on:
                texts.append(Element(reading.leak_status, measured, "I", reading.leakage).text())
            texts.append(Element(reading.status, measured, "C", reading.capacitance).text())
            if self.faults.garbage_at(index):
                texts[-1] = GARBAGE_ELEMENT
        if self._fmt_mode != 0:
            texts.append(Element("E" if is_last else "W", src.channel, "V", voltage).text())
        return texts

    def _qscv_end_action(self, src: QsvSource, post: int, stopped: bool) -> Callable[[bool], None]:
        """After the sweep the source forces start (post 1, an automatic abort or ``AB``) or stop (post 2) (PG
        p494-495)."""

        def apply(aborted: bool) -> None:
            value = src.start if aborted or stopped or post == 1 else src.stop
            state = self.state.channels[src.channel]
            if state.output_on:
                force_source(state, "V", value, src.comp)

        return apply

    # -- offset measurement --------------------------------------------------------------------------------------------

    def _measure_qscv_offset(self, src: QsvSource, measured: int, t0: float) -> Measurement:
        """``QSZ 2``: the capacitance of the open path (``QSCV_STRAY_F`` plus noise; the DUT takes no part) over one
        transition of ``cvoltage``; stored as the offset of ``measured``. Error 245 when the offset current exceeds the
        ``QSR`` range."""
        cinteg, linteg, *_ = self._qst
        vq2 = src.cvoltage if src.one_point is False else abs(src.stop - src.start)
        vq2 = min(vq2, abs(src.step)) if not src.one_point else vq2
        current = QSCV_STRAY_F * vq2 / cinteg
        if abs(current) > OVERRANGE * QSCV_RANGES[self._qsr]:
            raise flex.FlexError(ERR_QSZ_RANGE)
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:offset:{self.state.measurement_count}")
        self.state.measurement_count += 1
        current += self._qscv_noise(measured, current, cinteg, rng)
        value = current * cinteg / vq2
        self.state.qscv_offsets[measured] = value
        end = t0 + self.faults.slow_factor() * (2.0 * linteg + cinteg)
        return Measurement(t0, end, [end], [[Element("N", measured, "C", value).text()]], None, None, None)


__all__ = ["QSCV_MODE", "QSCV_RANGES", "QSCV_STRAY_F", "QscvUnit", "QsvSource"]
