"""SMU unit of the simulator: ranging, measurement modes, DC and staircase sources, the measurement engine.

``SmuUnit`` is a mixin of ``SimInstrument`` (``transport/sim/instrument.py``): its ``@handles`` methods are the SMU
FLEX handlers, registered by mnemonic, and ``XE`` evaluates spot (``MM 1``), staircase sweep (``MM 2``, with an
optional synchronous ``WSV``/``WSI`` source) and multi-channel sweep (``MM 16``, ``WNX`` sources) measurements on
the scenario circuit (``solve`` applies the compliances of voltage and current sources; ``_block`` formats one step).
It uses the dispatcher's shared state and helpers (``state``, ``faults``, ``circuit``, ``scenario``, ``_smu``,
``_channel_type``, ``_check_interlock``, ``_on_levels``, ``_on_currents``, ``_current``, ``_sync_devices``) and the
A/D converter settings of ``CoreUnit`` (``integration_time``, ``noise_multiplier``). ``MM`` and ``XE`` are
dispatched by measurement mode in ``units/cmu.py`` (WP8.1): the MFCMU modes there, every other mode to
``_cmd_mm``/``_cmd_xe`` here. Manual references (Programming Guide Ed. 15, physical PDF pages): ``RI`` 501;
``RV`` 503; ``MM`` 470-471; ``CMM`` 380; ``DV`` 396; ``DI`` 391-392; ``WV`` 568-569; ``WI`` 551-552; ``WSV`` 561-563;
``WSI`` 560-561; ``WNX`` 556-559; ``WNCC`` 556; ``WT`` 564-565; ``WM`` 552-553; ``XE`` 570; current/voltage source
limits Tables 4-6/4-7 (PDF 341-342); interlock in the high-voltage state 577; multi-channel sweep 102-103; errors
220, 223, 224 (PDF 578-579).
``MM 10`` (sampling) triggers are handed to ``SamplingUnit._start_sampling`` (``units/sampling.py``, WP7.4).

Current sources (``DI``, ``WI``, ``WSI``, ``WNX`` mode 2): the channel's voltage is solved so that its current equals
the programmed current, unless that needs more than the voltage compliance (then the channel sits at ±Vcomp and
reports ``C``). Voltage readings are noiseless (simulator convention); a current reading of a current source carries
the usual current noise. An SMU whose scenario slot declares an ASU (``SimSlot.asu``, WP7.1) accepts the ASU current
ranges (``flex.I_CODES_ASU``) in ``RI``, ``DV``, ``DI`` and the sweep sources; its ``SAP`` path is ``units/switch.py``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.devices import canonical_channel
from b1500_test_agent.transport.sim.faults import GARBAGE_ELEMENT
from b1500_test_agent.transport.sim.format import DUMMY_VALUE, Element, worst_status
from b1500_test_agent.transport.sim.state import ChannelState
from b1500_test_agent.transport.sim.units.base import DEFAULT_ICOMP, Measurement, Unsupported, handles

OVERRANGE = 1.15
"""Fixed current range overflow threshold, as a fraction of full scale (simulator convention)."""

MULTI_CHANNEL_SWEEP = 16
"""``MM 16``: multi-channel sweep (PDF 102, 471)."""

SOLVE_ROUNDS = 50
"""Most Gauss-Seidel rounds between current sources and voltage compliances in ``solve``."""

SOLVE_TOLERANCE_V = 1e-10
"""``solve`` stops when no current source moved its voltage by more than this."""

Forced = Literal["V", "I"]


def force_source(state: ChannelState, source: Forced, level: float, comp: float) -> None:
    """Program ``state`` to force ``level`` (V or A) with compliance ``comp`` (A or V; stored as magnitude)."""
    if source == "V":
        state.mode, state.voltage, state.icomp, state.current = "V", level, abs(comp), 0.0
    else:
        state.mode, state.current, state.vcomp, state.voltage = "I", level, abs(comp), 0.0


@dataclass(frozen=True)
class SweepSource:
    """One staircase source: the ``WV``/``WI`` primary, the ``WSV``/``WSI`` synchronous source or a ``WNX`` source.

    ``source`` is what it forces (``V``/``I``), ``comp`` the compliance magnitude (A for V, V for I)."""

    channel: int
    source: Forced
    start: float
    stop: float
    comp: float
    range: int = 0

    def values(self, mode: int, steps: int) -> list[float]:
        """Output values: linear or log (``mode`` 1/3 vs 2/4), single (start→stop) or double (start→stop→start,
        2·steps points); a log source with ``start`` = ``stop`` stays constant."""
        n = steps
        if n == 1:
            forward = [self.start]
        elif mode in (1, 3):
            forward = [self.start + (self.stop - self.start) * i / (n - 1) for i in range(n)]
        else:
            ratio = self.stop / self.start
            forward = [self.start * ratio ** (i / (n - 1)) for i in range(n)]
        return forward + forward[::-1] if mode in (3, 4) else forward


@dataclass(frozen=True)
class Sweep:
    """A staircase sweep: the primary source (``WV``/``WI``, PG PDF 568-569, 551-552), its mode (1-4) and number of
    steps, and the sources that follow it (``WSV``/``WSI`` in MM 2, ``WNX`` in MM 16)."""

    primary: SweepSource
    mode: int
    steps: int
    followers: tuple[SweepSource, ...] = ()

    @property
    def channel(self) -> int:
        return self.primary.channel

    @property
    def start(self) -> float:
        return self.primary.start

    @property
    def stop(self) -> float:
        return self.primary.stop

    @property
    def sources(self) -> tuple[SweepSource, ...]:
        """The primary first, then the followers."""
        return (self.primary, *self.followers)

    def values(self) -> list[float]:
        """The primary's output values."""
        return self.primary.values(self.mode, self.steps)

    def table(self) -> list[dict[int, float]]:
        """Per step: channel → output value of every source."""
        columns = {src.channel: src.values(self.mode, self.steps) for src in self.sources}
        return [{ch: values[i] for ch, values in columns.items()} for i in range(len(columns[self.channel]))]


def max_vcomp(current: float) -> float:
    """Maximum |Vcomp| (V) of an MP/HRSMU current source at ``current`` (Table 4-6, PDF 341): 100 V up to 20 mA, 40 V
    up to 50 mA, 20 V up to 100 mA; 0 beyond (no current source above 100 mA)."""
    magnitude = abs(current)
    if magnitude <= 0.02:
        return 100.0
    if magnitude <= 0.05:
        return 40.0
    if magnitude <= 0.1:
        return 20.0
    return 0.0


class SmuUnit:
    """SMU FLEX handlers and the measurement engine of ``SimInstrument`` (see the module docstring)."""

    def _reset_smu_settings(self) -> None:
        """Measurement mode, ranging and sweep setup to their initial settings (PG Table 2-13, PDF 180)."""
        self._mm: tuple[int, list[int]] | None = None
        self._cmm: dict[int, int] = {}
        self._ri: dict[int, int] = {}
        self._rv: dict[int, int] = {}
        self._sweep: Sweep | None = None
        self._sync: SweepSource | None = None
        self._wnx: dict[int, SweepSource] = {}
        self._wt = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._wm = (1, 1)

    # -- ranges and modes ----------------------------------------------------------------------------------------------

    def _i_codes(self, channel: int) -> range:
        """Current range codes of ``channel``'s module, with the ASU ranges when its slot has an ASU (WP7.1)."""
        module = self._channel_type(channel) or ""
        table = flex.I_CODES_ASU if self._has_asu(channel) else flex.I_CODES
        return table.get(module, range(0))

    @handles("RI")
    def _cmd_ri(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        if code != 0 and abs(code) not in self._i_codes(channel):
            raise flex.FlexError(flex.ERR_RANGE, f"RI {code} on {self._channel_type(channel)}")
        self._ri[channel] = code

    @handles("RV")
    def _cmd_rv(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        code = flex.integer(cmd.args[1])
        if code not in flex.V_MEAS_CODES:
            raise flex.FlexError(flex.ERR_RANGE, f"RV {code}")
        self._rv[channel] = code

    def _cmd_mm(self, cmd: flex.Command) -> None:
        """``MM 1|2|10|16,ch...``: spot, staircase sweep, sampling (``units/sampling.py``) or multi-channel sweep;
        other modes are unsupported (PDF 470-471)."""
        if not cmd.args:
            raise flex.FlexError(flex.ERR_TERMINATOR)
        mode = flex.integer(cmd.args[0])
        if not 1 <= mode <= 28:
            raise flex.FlexError(flex.ERR_PARAMETER)
        if mode not in (1, 2, 10, MULTI_CHANNEL_SWEEP):
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
        if irange != 0 and irange not in self._i_codes(channel):
            raise flex.FlexError(flex.ERR_RANGE, f"irange {irange}")
        self._check_interlock(voltage)
        force_source(state, "V", voltage, icomp)
        state.comp_polarity, state.vrange, state.irange = polarity, vrange, irange

    @handles("DI")
    def _cmd_di(self, cmd: flex.Command) -> None:
        """``DI chnum,irange,current[,Vcomp[,comp_polarity[,vrange]]]`` (PDF 391-392); limits Table 4-6 (PDF 341)."""
        flex.arity(cmd, 3, 6)
        channel = self._smu(cmd.args[0])
        state = self.state.channels[channel]
        if not state.output_on:
            raise flex.FlexError(flex.ERR_OUTPUT_OFF)
        irange = self._output_irange(channel, cmd.args[1])
        current = flex.number(cmd.args[2])
        vcomp = flex.number(cmd.args[3]) if len(cmd.args) > 3 else state.vcomp
        if vcomp is None or vcomp == 0 or abs(vcomp) > max_vcomp(current):
            raise flex.FlexError(flex.ERR_DV_COMPLIANCE, f"Vcomp {vcomp} at {current} A")
        polarity = flex.integer(cmd.args[4]) if len(cmd.args) > 4 else 0
        if polarity not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        vrange = flex.integer(cmd.args[5]) if len(cmd.args) > 5 else 0
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"vrange {vrange}")
        self._check_interlock(vcomp)
        force_source(state, "I", current, vcomp)
        state.comp_polarity, state.vrange, state.irange = polarity, vrange, irange

    def _output_irange(self, channel: int, arg: str) -> int:
        """A current output ranging code of ``channel``'s module (Table 4-5, PDF 340): 0 or the module's ranges."""
        code = flex.integer(arg)
        if code != 0 and code not in self._i_codes(channel):
            raise flex.FlexError(flex.ERR_RANGE, f"irange {code} on {self._channel_type(channel)}")
        return code

    @handles("WV")
    def _cmd_wv(self, cmd: flex.Command) -> None:
        """``WV chnum,mode,range,start,stop,step[,Icomp[,Pcomp]]`` (PDF 568-569); Pcomp is unsupported. Clears the
        ``WI``, ``WSV``/``WSI`` and ``WNX`` settings."""
        flex.arity(cmd, 6, 8)
        channel = self._smu(cmd.args[0])
        mode = self._sweep_mode(cmd.args[1])
        vrange = flex.integer(cmd.args[2])
        if vrange not in flex.V_RANGE_MAX:
            raise flex.FlexError(flex.ERR_RANGE, f"range {vrange}")
        start, stop = self._levels(cmd.args[3], cmd.args[4], mode)
        steps = self._steps(cmd.args[5])
        if len(cmd.args) > 7:
            raise Unsupported("WV power compliance (Pcomp)")
        icomp = self._v_comp_arg(cmd.args[6] if len(cmd.args) > 6 else None, channel, max(abs(start), abs(stop)))
        self._sweep = Sweep(SweepSource(channel, "V", start, stop, abs(icomp), vrange), mode, steps)
        self._sync, self._wnx = None, {}

    @handles("WI")
    def _cmd_wi(self, cmd: flex.Command) -> None:
        """``WI chnum,mode,range,start,stop,step[,Vcomp[,Pcomp]]`` (PDF 551-552); Pcomp is unsupported. Clears the
        ``WV``, ``WSV``/``WSI`` and ``WNX`` settings."""
        flex.arity(cmd, 6, 8)
        channel = self._smu(cmd.args[0])
        mode = self._sweep_mode(cmd.args[1])
        irange = self._output_irange(channel, cmd.args[2])
        start, stop = self._levels(cmd.args[3], cmd.args[4], mode, current=True)
        steps = self._steps(cmd.args[5])
        if len(cmd.args) > 7:
            raise Unsupported("WI power compliance (Pcomp)")
        vcomp = self._i_comp_arg(cmd.args[6] if len(cmd.args) > 6 else None, channel, max(abs(start), abs(stop)))
        self._sweep = Sweep(SweepSource(channel, "I", start, stop, abs(vcomp), irange), mode, steps)
        self._sync, self._wnx = None, {}

    @handles("WSV", "WSI")
    def _cmd_wsync(self, cmd: flex.Command) -> None:
        """``WSV chnum,range,start,stop[,Icomp[,Pcomp]]`` / ``WSI chnum,range,start,stop[,Vcomp[,Pcomp]]`` (PDF
        560-563): the synchronous source of the primary sweep (error 220 without one); sweep mode and steps are the
        primary's. The output-mode match is checked at ``XE`` (error 224)."""
        flex.arity(cmd, 4, 6)
        source: Forced = "V" if cmd.mnemonic == "WSV" else "I"
        self._sync = self._follower(cmd.mnemonic, source, cmd.args[0], cmd.args[1], cmd.args[2], cmd.args[3],
                                    cmd.args[4:])

    @handles("WNX")
    def _cmd_wnx(self, cmd: flex.Command) -> None:
        """``WNX N,chnum,mode,range,start,stop[,comp[,Pcomp]]`` (PDF 556-559): sweep source ``N`` (2-10) of the
        multi-channel sweep, after ``WV``/``WI`` (error 220 otherwise); a repeated ``N`` or channel replaces the
        earlier setting. ``N`` = 1 belongs to MM 28 (not simulated)."""
        flex.arity(cmd, 6, 8)
        n = flex.integer(cmd.args[0])
        if not 1 <= n <= 10:
            raise flex.FlexError(flex.ERR_PARAMETER, f"N {n}")
        if n == 1:
            raise Unsupported("WNX N=1 (multi-channel pulsed sweep MM 28)")
        mode = flex.integer(cmd.args[2])
        if mode not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {mode}")
        source: Forced = "V" if mode == 1 else "I"
        item = self._follower("WNX", source, cmd.args[1], cmd.args[3], cmd.args[4], cmd.args[5], cmd.args[6:])
        self._wnx = {k: v for k, v in self._wnx.items() if v.channel != item.channel}
        self._wnx[n] = item

    @handles("WNCC")
    def _cmd_wncc(self, cmd: flex.Command) -> None:
        """``WNCC``: clear the multi-channel sweep setup (``WNX``; PDF 556)."""
        flex.arity(cmd, 0, 0)
        self._wnx = {}

    def _sweep_mode(self, arg: str) -> int:
        mode = flex.integer(arg)
        if mode not in (1, 2, 3, 4):
            raise flex.FlexError(flex.ERR_PARAMETER, f"mode {mode}")
        return mode

    @staticmethod
    def _steps(arg: str) -> int:
        steps = flex.integer(arg)
        if not 1 <= steps <= 10001:
            raise flex.FlexError(flex.ERR_PARAMETER, f"step {steps}")
        return steps

    @staticmethod
    def _levels(start_arg: str, stop_arg: str, mode: int | None, *, current: bool = False) -> tuple[float, float]:
        """Start and stop of a source: within the module's output (100 V or 100 mA, Tables 4-6/4-7) and, for a log
        sweep (``mode`` 2/4), non-zero with one polarity (error 130)."""
        start, stop = flex.number(start_arg), flex.number(stop_arg)
        peak = max(abs(start), abs(stop))
        if peak > (flex.SMU_MAX_I if current else flex.SMU_MAX_V):
            raise flex.FlexError(flex.ERR_PARAMETER, f"{peak} {'A' if current else 'V'}")
        if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0)):
            raise flex.FlexError(flex.ERR_LOG_POLARITY)
        return start, stop

    def _v_comp_arg(self, arg: str | None, channel: int, peak_v: float) -> float:
        """Icomp of a voltage sweep source (the previous value when omitted; error 223 when unset or invalid); the
        interlock must be closed above 42 V."""
        icomp = flex.number(arg) if arg is not None else self.state.channels[channel].icomp
        if icomp is None or icomp == 0 or abs(icomp) > flex.max_icomp(peak_v):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Icomp {icomp}")
        self._check_interlock(peak_v)
        return icomp

    def _i_comp_arg(self, arg: str | None, channel: int, peak_i: float) -> float:
        """Vcomp of a current sweep source (the previous value when omitted; error 223 when unset or invalid); the
        interlock must be closed when Vcomp exceeds 42 V."""
        vcomp = flex.number(arg) if arg is not None else self.state.channels[channel].vcomp
        if vcomp is None or vcomp == 0 or abs(vcomp) > max_vcomp(peak_i):
            raise flex.FlexError(flex.ERR_SWEEP_COMPLIANCE, f"Vcomp {vcomp}")
        self._check_interlock(vcomp)
        return vcomp

    def _follower(self, mnemonic: str, source: Forced, channel_arg: str, range_arg: str, start_arg: str,
                  stop_arg: str, rest: tuple[str, ...]) -> SweepSource:
        """A ``WSV``/``WSI``/``WNX`` source: needs a primary sweep (error 220), the primary's log polarity rule."""
        if self._sweep is None:
            raise flex.FlexError(flex.ERR_NO_SWEEP, f"{mnemonic} before WV/WI")
        channel = self._smu(channel_arg)
        if source == "V":
            rng = flex.integer(range_arg)
            if rng not in flex.V_RANGE_MAX:
                raise flex.FlexError(flex.ERR_RANGE, f"range {rng}")
        else:
            rng = self._output_irange(channel, range_arg)
        start, stop = self._levels(start_arg, stop_arg, self._sweep.mode, current=source == "I")
        if len(rest) > 1:
            raise Unsupported(f"{mnemonic} power compliance (Pcomp)")
        comp_arg = rest[0] if rest else None
        peak = max(abs(start), abs(stop))
        comp = self._v_comp_arg(comp_arg, channel, peak) if source == "V" else self._i_comp_arg(comp_arg, channel,
                                                                                                    peak)
        return SweepSource(channel, source, start, stop, abs(comp), rng)

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

    def solve(self, levels: dict[int, float], icomps: dict[int, float],
              forced: dict[int, tuple[float, float]] | None = None) -> tuple[dict[int, float], dict[int, float],
                                                                             set[int]]:
        """Applied voltages, channel currents and the channels in compliance for programmed voltage ``levels``
        (compliance ``icomps``) and current sources ``forced`` (channel → (current, Vcomp)).

        A voltage channel whose |I| would exceed its compliance has its applied voltage bisected (between the
        programmed level and 0 V, or beyond 0 V when another biased terminal still drives more than Icomp there,
        e.g. through a gate-drain short) until |I| = Icomp; this repeats for the next channel in compliance. A
        current source gets the voltage at which its current equals the programmed one (bisection within ±Vcomp; at
        ±Vcomp, in compliance, when that is not enough). With both kinds, the two steps alternate (Gauss-Seidel)
        until no current source moves by more than ``SOLVE_TOLERANCE_V``. The devices are passive, so a channel's
        current rises monotonically with its own voltage. The returned voltages cover both kinds of channel.
        """
        if not forced:
            return self._solve_voltages(levels, icomps, {})
        fixed = {ch: 0.0 for ch in forced}
        limited: set[int] = set()
        for _ in range(SOLVE_ROUNDS):
            applied, _, _ = self._solve_voltages(levels, icomps, fixed)
            moved = 0.0
            limited = set()
            for channel, (target, vcomp) in forced.items():
                voltage, at_limit = self._force_current(applied, channel, target, vcomp)
                moved = max(moved, abs(voltage - applied[channel]))
                applied[channel] = fixed[channel] = voltage
                if at_limit:
                    limited.add(channel)
            if moved <= SOLVE_TOLERANCE_V:
                break
        applied, currents, clamped = self._solve_voltages(levels, icomps, fixed)
        return applied, currents, clamped | limited

    def _solve_voltages(self, levels: dict[int, float], icomps: dict[int, float],
                        fixed: dict[int, float]) -> tuple[dict[int, float], dict[int, float], set[int]]:
        """``solve`` for the voltage channels, with the current sources held at the voltages ``fixed``."""
        applied = {**levels, **fixed}
        clamped: set[int] = set()
        for _ in range(len(levels)):
            currents = self._current(applied)
            over = [ch for ch in levels
                    if ch not in clamped and abs(currents.get(ch, 0.0)) > icomps[ch] * (1 + 1e-12)]
            if not over:
                break
            channel = max(over, key=lambda ch: abs(currents[ch]) / icomps[ch])
            applied[channel] = self._bisect(applied, channel, icomps[channel])
            clamped.add(channel)
        return applied, self._current(applied), clamped

    def _force_current(self, applied: dict[int, float], channel: int, target: float,
                       vcomp: float) -> tuple[float, bool]:
        """Voltage of current source ``channel`` delivering ``target`` A with the others at ``applied``, and whether
        it sits at the voltage compliance (the current needs more than ±|Vcomp|). A device that draws no current
        at all (an open) leaves a 0 A source at 0 V."""
        def current(voltage: float) -> float:
            trial = dict(applied)
            trial[channel] = voltage
            return self._current(trial).get(channel, 0.0)

        limit = abs(vcomp)
        top, bottom = current(limit), current(-limit)
        tolerance = 1e-12 * abs(target) + 1e-18
        if target > top + tolerance:
            return limit, True
        if target < bottom - tolerance:
            return -limit, True
        if abs(top - bottom) <= tolerance:  # no voltage dependence (open): nothing to settle against
            return 0.0, False
        return _bracketed_root(current, target, -limit, limit, bottom, top), False

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

    def _cmd_xe(self, cmd: flex.Command) -> None:
        """``XE``: trigger the ``MM`` measurement (PDF 570); errors 214, 220, 224, 200."""
        flex.arity(cmd, 0, 0)
        if self._mm is None:
            raise flex.FlexError(flex.ERR_NO_MM)
        mode, channels = self._mm
        if mode == 10:
            self._start_sampling(channels)
            return
        sweep = self._staircase(mode)
        for channel in [*channels, *(src.channel for src in sweep.sources)] if sweep else channels:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        self._measurement = self._measure(channels, sweep, self._now())
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    def _staircase(self, mode: int) -> Sweep | None:
        """The sweep of MM 2 (primary + synchronous source) or MM 16 (primary + ``WNX`` sources in ``N`` order);
        ``None`` for a spot measurement. Error 220 without a primary; 224 when the synchronous source has another
        output mode than the primary or sits on the primary's channel (PDF 579)."""
        if mode == 1:
            return None
        if self._sweep is None:
            raise flex.FlexError(flex.ERR_NO_SWEEP)
        primary = self._sweep.primary
        if mode == 2:
            followers = (self._sync,) if self._sync is not None else ()
            if self._sync is not None and (self._sync.source != primary.source or self._sync.channel ==
                                           primary.channel):
                raise flex.FlexError(flex.ERR_SYNC_MODE)
        else:
            followers = tuple(self._wnx[n] for n in sorted(self._wnx))
            if any(item.channel == primary.channel for item in followers):
                raise flex.FlexError(flex.ERR_SYNC_MODE, "WNX source on the primary channel")
        return Sweep(primary, self._sweep.mode, self._sweep.steps, followers)

    def _measure(self, channels: list[int], sweep: Sweep | None, t0: float) -> Measurement:
        factor = self.faults.slow_factor()
        hold, delay, sdelay = self._wt[0], self._wt[1], self._wt[2]
        tmeas = {ch: self.integration_time(ch) for ch in channels}
        meas_total = sum(tmeas.values())
        table: list[dict[int, float] | None] = list(sweep.table()) if sweep else [None]
        levels0 = self._on_levels()
        currents0 = self._on_currents()
        icomps = {ch: self._icomp(ch) for ch in levels0}
        sources = {src.channel: src for src in sweep.sources} if sweep else {}
        for channel, src in sources.items():
            if src.source == "V":
                currents0.pop(channel, None)
                icomps[channel] = src.comp
            else:
                levels0.pop(channel, None)
                icomps.pop(channel, None)
        noise = self.scenario.noise
        rng = random.Random(f"{noise.seed}:{self.state.measurement_count}")
        self.state.measurement_count += 1
        blocks: list[list[str]] = []
        step_ends: list[float] = []
        device_states = [self.circuit.export_state()] if self.circuit.has_state else []
        aborted = False
        zero_at: float | None = None
        last = len(table) - 1
        period = delay + max(meas_total, sdelay)
        for i, row in enumerate(table):
            if sweep:  # hold, then per step: force, wait delay, measure; next step after max(meas, Sdelay)
                meas_start, nominal_end = hold + i * period + delay, hold + (i + 1) * period
            else:
                meas_start, nominal_end = 0.0, meas_total
            end = t0 + factor * nominal_end
            step_ends.append(end)
            stamp = t0 + factor * meas_start - self._timer_zero
            levels = dict(levels0)
            forced = dict(currents0)
            for channel, value in (row or {}).items():
                if sources[channel].source == "V":
                    levels[channel] = value
                else:
                    forced[channel] = (value, sources[channel].comp)
            if not aborted and self.faults.interlock_opens_at(i):
                self._interlock_open = True
            potentials = {**levels, **{ch: vcomp for ch, (_, vcomp) in forced.items()}}
            if not aborted and self.interlock_open() and self._high_voltage(potentials):
                # interlock opened in the high-voltage state: all outputs to 0 V, error 202 (PG PDF 577)
                self._queue_error(flex.ERR_INTERLOCK)
                zero_at = end
                aborted = True
            if aborted:
                blocks.append(self._dummy_block(channels, sweep, stamp, i == last))
                continue
            value = row[sweep.channel] if sweep and row is not None else None
            block, statuses, applied = self._block(channels, sweep, value, levels, icomps, tmeas, stamp, i, last, rng,
                                                   forced)
            blocks.append(block)
            if self.circuit.has_state:  # the step's voltages act on the device before the next step
                self.circuit.commit(applied)
                device_states.append(self.circuit.export_state())
            if self._wm[0] == 2 and any(s in "CTVX" for s in statuses):
                aborted = True  # automatic abort: later steps carry dummy data (PDF 553)
        post: float | None = None
        post_at_stop = False
        if sweep is not None:
            post_at_stop = self._wm[1] == 2 and not aborted
            post = sweep.stop if post_at_stop else sweep.start
        self._sync_devices()
        return Measurement(t0, step_ends[-1], step_ends, blocks, sweep, post, zero_at, device_states,
                           post_at_stop=post_at_stop)

    def _quantity(self, channel: int, forced: dict[int, tuple[float, float]]) -> Forced:
        """What ``CMM`` makes ``channel`` measure: 1 current, 2 voltage, 0 the compliance side (a voltage source
        measures I, a current source V), 3 the force side (PDF 380)."""
        mode = self._cmm.get(channel, 0)
        forces_current = channel in forced
        if mode == 1:
            return "I"
        if mode == 2:
            return "V"
        if mode == 3:
            return "I" if forces_current else "V"
        return "V" if forces_current else "I"

    def _block(self, channels: list[int], sweep: Sweep | None, value: float | None, levels: dict[int, float],
               icomps: dict[int, float], tmeas: dict[int, float], stamp: float, step: int, last: int,
               rng: random.Random, forced: dict[int, tuple[float, float]] | None = None,
               ) -> tuple[list[str], list[str], dict[int, float]]:
        forced = forced or {}
        applied, currents, clamped = self.solve(levels, icomps, forced)
        faulted = {canonical_channel(ch) for ch in self.faults.compliance_channels(step)}
        limited = clamped | faulted
        oscillating = self.faults.oscillating(step)
        texts: list[str] = []
        statuses: list[str] = []
        offset = 0.0
        for channel in channels:
            quantity = self._quantity(channel, forced)
            status = "C" if channel in limited else ("T" if limited else "N")
            if quantity == "I":
                reading = currents.get(channel, 0.0)
                if channel in faulted and channel not in forced:
                    sign = reading if reading != 0 else (applied.get(channel, 0.0) or 1.0)
                    reading = math.copysign(icomps.get(channel, DEFAULT_ICOMP), sign)
                else:
                    reading += self._noise(channel, reading, rng)
                code = self._ri.get(channel, 0)
                if code < 0 and abs(reading) > OVERRANGE * flex.current_range(code):
                    status = worst_status([status, "V"])
            else:
                reading = applied.get(channel, 0.0)
                if channel in faulted and channel in forced:
                    target, vcomp = forced[channel]
                    reading = math.copysign(vcomp, target if target != 0 else 1.0)
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
            texts.append(Element("E" if step == last else "W", sweep.channel, sweep.primary.source, value).text())
        return texts, statuses, applied

    def _dummy_block(self, channels: list[int], sweep: Sweep | None, stamp: float, is_last: bool) -> list[str]:
        forced = self._on_currents()
        if sweep is not None:
            for src in sweep.sources:
                if src.source == "I":
                    forced[src.channel] = (src.start, src.comp)
                else:
                    forced.pop(src.channel, None)
        texts: list[str] = []
        for channel in channels:
            quantity = self._quantity(channel, forced)
            if self._tsc:
                texts.append(Element("N", channel, "T", stamp).text())
            texts.append(Element("V", channel, quantity, DUMMY_VALUE).text())
        if sweep is not None and self._fmt_mode == 1:
            texts.append(Element("E" if is_last else "W", sweep.channel, sweep.primary.source, DUMMY_VALUE).text())
        return texts

    def _noise(self, channel: int, current: float, rng: random.Random) -> float:
        noise = self.scenario.noise
        module = self._channel_type(channel)
        floor = noise.floor_a.get(module, 0.0) if module else 0.0
        sigma = self.noise_multiplier(channel) * math.hypot(floor, noise.rel * current)
        return rng.gauss(0.0, sigma) if sigma > 0 else 0.0


def _bracketed_root(f: Callable[[float], float], target: float, lo: float, hi: float, f_lo: float,
                    f_hi: float) -> float:
    """The ``x`` in ``[lo, hi]`` where the increasing ``f`` equals ``target`` (``f_lo <= target <= f_hi``): Illinois
    (modified regula falsi) steps, with a bisection step whenever an interpolation step did not shrink the bracket by
    half, until the bracket is below 0.1 pV or ``f`` hits ``target`` within 1e-12 relative; the last step
    interpolates linearly (exact on a resistor)."""
    side = 0
    for _ in range(200):
        width = hi - lo
        if width < 1e-13:
            break
        if f_hi != f_lo:
            x = lo + (target - f_lo) * width / (f_hi - f_lo)
            if not lo < x < hi:
                x = 0.5 * (lo + hi)
        else:
            x = 0.5 * (lo + hi)
        fx = f(x)
        if abs(fx - target) <= 1e-12 * abs(target) + 1e-21:
            return x
        if fx > target:
            hi, f_hi = x, fx
            if side == 1:
                f_lo = target + (f_lo - target) / 2  # Illinois: the stale end counts half
            side = 1
        else:
            lo, f_lo = x, fx
            if side == -1:
                f_hi = target + (f_hi - target) / 2
            side = -1
        if hi - lo > 0.5 * width:  # slow progress: bisect once
            mid = 0.5 * (lo + hi)
            f_mid = f(mid)
            if f_mid > target:
                hi, f_hi = mid, f_mid
            else:
                lo, f_lo = mid, f_mid
            side = 0
    if f_hi == f_lo:
        return 0.5 * (lo + hi)
    return lo + (target - f_lo) * (hi - lo) / (f_hi - f_lo)
