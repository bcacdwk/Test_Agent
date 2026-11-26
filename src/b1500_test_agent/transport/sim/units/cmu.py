"""MFCMU unit of the simulator (blueprint v2 4.1, 4.2 "fixture + capacitor", 4.3; WP8.1).

``CmuUnit`` is a mixin of ``SimInstrument``; the measurement physics, routing and data formatting live in its base
``CmuEngine`` (``units/cmu_engine.py``). The unit owns the MFCMU state:

- signal and setup (per process, reset by ``*RST``/device clear to the initial settings of Table 2-13, PDF 180):
  ``FC``/``ACV``/``DCV`` act on the channel's output state (``ChannelState.freq_hz``/``ac_vrms``/``voltage``, only
  with the output switch on, error 200), ``IMP``, ``LMN``, ``ACT``, ``RC`` and the sources and timing of MM 18-26
  (``WDCV``/``WTDCV``/``WMDCV``, ``WFC``/``WTFC``/``WMFC``, ``WACV``/``WTACV``/``WMACV``, ``PDCV``/``PTDCV``/``PWDCV``,
  ``MDCV``/``MTDCV``) with the manual's parameter domains (PG PDF 354-355, 379-391, 435, 441, 445, 467-477, 484-490,
  500, 547-568);
- correction state (persisted in ``SimPersistentState``, it survives host sessions): the correction functions
  (``cmu_corrections``; ``CORRST``, error 685 without data), the phase compensation mode and results (``ADJ``,
  ``ADJ?`` mode 1 needs the manual mode, error 680, takes 30 s and initializes the MFCMU), the frequency list
  (``CORRL``, ``CLCORR``), the standards' reference values (``DCORR``, error 682 for a wrong mode) and the data
  (``CORR?`` reads every listed frequency with the standard the human connected, error 684 at AC 0 V; ``CORRDT``
  sets data directly); ``CORRL?`` and ``DCORR?`` read the list and the references back (WP8.2), ``CORRDT?``
  the data of one listed frequency (WP8.6). ``CORRL``,
  ``CLCORR`` and ``DCORR`` switch the functions off and clear the data (PG PDF 379, 382, 384, 389). ``*RST`` and a
  device clear switch every function off and the compensation mode back to auto; the data, list, references and
  compensation results stay (PG PDF 382, 388; Table 2-13). The ``cmu_correction_lost`` fault clears all of it, as a
  power cycle of the module would. ATV-21 (corrections persist until ``*RST`` or a power cycle and ``CORRST?`` reflects
  them): as the manual states (same fact as ``catalog/kinds/cmu_correction.py``, "Hardware-bound").

``MM``/``XE`` dispatch by measurement mode (the WP5.2 handoff: "a second family that brings its own MM modes takes
over"): the MFCMU modes 17-26 are set up and triggered here, every other mode goes to ``SmuUnit``. MM 18 takes the
MFCMU first and up to nine SMUs (measured at every step, data after the MFCMU's, PG PDF 471); the others exactly
one MFCMU (error 322 for an SMU). Missing sources: errors 280 (WDCV), 281 (PDCV), 282 (PWDCV), 290 (WFC), 120 for
MM 23 without ``WACV`` and MM 26 without ``MDCV`` (no code listed); pulse width too short for the frequency: 284
(PG PDF 582). ``*LRN?`` types 70 ``IMP``, 71 ``LMN``, 72 ``ACT``, 73 ``RC``, 90 ``ADJ`` (PG PDF 452) are answered here.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.state import ChannelState, CmuCorrectionPoint
from b1500_test_agent.transport.sim.units.base import CMU_TYPES, Unsupported, handles, learns
from b1500_test_agent.transport.sim.units.cmu_engine import (
    CMU_MODES,
    CORR_POINT_S,
    IMP_TABLE,
    PHASE_COMPENSATION_S,
    CmuEngine,
    CmuStep,
)

CORRECTION_MODES = (1, 2, 3)
"""``CORRST``/``CORR?``/``DCORR`` correction modes: 1 open, 2 short, 3 load (PG PDF 388)."""

PHASE_NOT_PERFORMED = 3
"""``ADJ?`` result when no phase compensation measurement has been performed (PG PDF 356)."""

DCORR_MODE = {1: 100, 2: 400, 3: 400}
"""``DCORR`` mode per standard: Cp-G for the open, Ls-Rs for the short and the load (PG PDF 389)."""

DEFAULT_FREQS = (1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6, 1.2e6, 1.5e6, 2e6, 2.5e6, 2.7e6, 3e6, 3.2e6, 3.5e6,
                 3.7e6, 4e6, 4.2e6, 4.5e6, 5e6)
"""``CLCORR chnum,2`` default correction frequencies (PG PDF 379)."""

F_MIN, F_MAX = 1.0e3, 5.0e6
AC_MAX, DC_MAX, STEPS_MAX = 0.25, 25.0, 1001
TIMING_LIMITS = {"WTDCV": 65.535, "WTFC": 655.35, "WTACV": 655.35}
"""Largest ``delay`` per sweep timing command (PG PDF 565-568); hold 655.35, Sdelay 1, Mdelay 65.535 for all."""


def _sweep_values(mode: int, start: float, stop: float, steps: int) -> list[float]:
    if steps == 1:
        forward = [start]
    elif mode in (1, 3):
        forward = [start + (stop - start) * i / (steps - 1) for i in range(steps)]
    else:
        forward = [start * (stop / start) ** (i / (steps - 1)) for i in range(steps)]
    return forward + forward[::-1] if mode in (3, 4) else forward


def _pulse_min_width(f: float) -> float:
    """Shortest ``PTDCV`` width at MFCMU frequency ``f`` (PG PDF 488)."""
    return 0.05 if f <= 1e4 else 0.01 if f <= 2e5 else 0.008


class CmuUnit(CmuEngine):
    """MFCMU FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_cmu_settings(self) -> None:
        """Measurement parameter, ranging, averaging, monitor, sources and timing to their initial settings (PG
        Table 2-13, PDF 180: Cp-G, auto range, auto averaging, sources cleared, timing 0)."""
        self._imp = 100
        self._lmn = False
        self._act: tuple[int, int] = (0, 2)
        self._rc: dict[int, tuple[int, int]] = {}
        self._wdcv: tuple[int, int, float, float, int] | None = None
        self._wfc: tuple[int, int, float, float, int] | None = None
        self._wacv: tuple[int, int, float, float, int] | None = None
        self._cmu_timing = {name: (0.0, 0.0, 0.0, 0.0, 0.0) for name in TIMING_LIMITS}
        self._cmu_abort = {"WMDCV": (1, 1), "WMFC": (1, 1), "WMACV": (1, 1)}
        self._pdcv: tuple[int, float, float] | None = None
        self._ptdcv: tuple[float, float, float, float] = (0.0, 0.008, 0.01, 0.0)
        self._pwdcv: tuple[int, int, float, float, float, int] | None = None
        self._mdcv: tuple[int, float, float] | None = None
        self._mdcv_post = 0.0
        self._mtdcv: tuple[float, float, int, float] = (0.0, 0.01, 1000, 0.0)
        self._cmu_dc_override: dict[int, float] | None = None

    def _reset_cmu_state(self) -> None:
        """``*RST``/device clear: every correction function OFF, phase compensation mode auto (PG PDF 388, Table
        2-13); data, list, references and compensation results stay."""
        self.state.cmu_corrections.clear()
        for persistent in self.state.cmu.values():
            persistent.adj_mode = 0

    def _lose_cmu_corrections(self) -> None:
        """The ``cmu_correction_lost`` fault: every MFCMU forgets its corrections and phase compensation, as after a
        power cycle of the module (blueprint v2 4.3)."""
        self.state.cmu_corrections.clear()
        self.state.cmu_phase_results.clear()
        self.state.cmu.clear()

    # -- helpers --------------------------------------------------------------------------------------------------

    def _cmu_channel(self, arg: str) -> int:
        """An MFCMU channel argument (errors 121/153; 322 for an SMU, 151 for any other module)."""
        number = flex.integer(arg)
        module = self._channel_type(number if number <= 10 else number // 100) if 1 <= number <= 1002 else None
        if module is not None and module not in CMU_TYPES and module.endswith("SMU"):
            raise flex.FlexError(flex.ERR_NOT_FOR_SMU, f"channel {number} is a {module}")
        return self._channel(arg, kinds=CMU_TYPES)

    def _cmu_enabled(self, arg: str) -> tuple[int, ChannelState]:
        channel = self._cmu_channel(arg)
        state = self.state.channels[channel]
        if not state.output_on:
            raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        return channel, state

    @staticmethod
    def _value(arg: str, low: float, high: float, what: str) -> float:
        value = flex.number(arg)
        if not low <= value <= high:
            raise flex.FlexError(flex.ERR_PARAMETER, f"{what} {value}")
        return value

    def _dc_value(self, arg: str, what: str) -> float:
        value = flex.number(arg)
        if abs(value) > DC_MAX:
            if abs(value) <= 100.0:
                raise Unsupported(f"{what} {value} V needs the SCUU SMU (not simulated; out of scope, blueprint v2 "
                                  "1.2)")
            raise flex.FlexError(flex.ERR_PARAMETER, f"{what} {value}")
        return value

    def _steps_arg(self, arg: str) -> int:
        steps = flex.integer(arg)
        if not 1 <= steps <= STEPS_MAX:
            raise flex.FlexError(flex.ERR_PARAMETER, f"step {steps}")
        return steps

    def _initialize_cmu(self, channel: int) -> None:
        """``ADJ``/``ADJ?`` initialize the MFCMU: DC 0 V, AC 0 V, 1 kHz, auto range (output switch unchanged)."""
        state = self.state.channels.setdefault(channel, ChannelState())
        if not self.faults.stuck(channel):
            state.voltage, state.ac_vrms, state.freq_hz = 0.0, 0.0, 1000.0
        self._rc.pop(channel, None)

    def _corrections_off(self, channel: int, *, clear_data: bool) -> None:
        self.state.cmu_corrections.pop(channel, None)
        if clear_data:
            self._cmu_persistent(channel).data.clear()

    # -- signal, parameter, ranging, averaging, monitor -----------------------------------------------------------

    @handles("FC")
    def _cmd_fc(self, cmd: flex.Command) -> None:
        """``FC chnum,freq``: 1 kHz to 5 MHz (PG PDF 435, Table 4-18)."""
        flex.arity(cmd, 2, 2)
        _, state = self._cmu_enabled(cmd.args[0])
        state.freq_hz = self._value(cmd.args[1], F_MIN, F_MAX, "FC freq")

    @handles("ACV")
    def _cmd_acv(self, cmd: flex.Command) -> None:
        """``ACV chnum,voltage``: 0 to 0.25 V rms (PG PDF 354-355)."""
        flex.arity(cmd, 2, 2)
        _, state = self._cmu_enabled(cmd.args[0])
        state.ac_vrms = self._value(cmd.args[1], 0.0, AC_MAX, "ACV")

    @handles("DCV")
    def _cmd_dcv(self, cmd: flex.Command) -> None:
        """``DCV chnum,voltage``: 0 to +-25 V from the MFCMU (PG PDF 390-391)."""
        flex.arity(cmd, 2, 2)
        _, state = self._cmu_enabled(cmd.args[0])
        state.voltage = self._dc_value(cmd.args[1], "DCV")

    @handles("IMP")
    def _cmd_imp(self, cmd: flex.Command) -> None:
        """``IMP mode`` (Table 4-16, PDF 347; PG PDF 441)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in IMP_TABLE:
            raise flex.FlexError(flex.ERR_PARAMETER, f"IMP {mode}")
        self._imp = mode

    @handles("LMN")
    def _cmd_lmn(self, cmd: flex.Command) -> None:
        """``LMN 0|1`` (PG PDF 445)."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"LMN {mode}")
        self._lmn = mode == 1

    @handles("ACT")
    def _cmd_act(self, cmd: flex.Command) -> None:
        """``ACT mode[,N]``: mode 0 N 1-1023 (default 2), mode 2 N 1-100 (default 1) (PG PDF 354)."""
        flex.arity(cmd, 1, 2)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ACT mode {mode}")
        n = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else (2 if mode == 0 else 1)
        if not 1 <= n <= (1023 if mode == 0 else 100):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ACT N {n}")
        self._act = (mode, n)

    @handles("RC")
    def _cmd_rc(self, cmd: flex.Command) -> None:
        """``RC chnum,mode[,range]``: 0 auto, 2 fixed with a range >= 0 (PG PDF 500, Table 4-17)."""
        flex.arity(cmd, 2, 3)
        channel = self._cmu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode == 0 and len(cmd.args) == 2:
            self._rc.pop(channel, None)
            return
        if mode != 2 or len(cmd.args) != 3 or flex.integer(cmd.args[2]) < 0:
            raise flex.FlexError(flex.ERR_PARAMETER, f"RC {','.join(cmd.args)}")
        self._rc[channel] = (2, flex.integer(cmd.args[2]))

    # -- sweep, pulse and sampling sources ------------------------------------------------------------------------

    def _sweep_source(self, cmd: flex.Command, low: float, high: float, what: str,
                      ) -> tuple[int, int, float, float, int]:
        flex.arity(cmd, 5, 5)
        channel, _ = self._cmu_enabled(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (1, 2, 3, 4):
            raise flex.FlexError(flex.ERR_PARAMETER, f"{what} mode {mode}")
        start, stop = self._value(cmd.args[2], low, high, what), self._value(cmd.args[3], low, high, what)
        if mode in (2, 4) and (start == 0 or stop == 0 or (start > 0) != (stop > 0)):
            raise flex.FlexError(flex.ERR_LOG_POLARITY)
        return channel, mode, start, stop, self._steps_arg(cmd.args[4])

    @handles("WDCV")
    def _cmd_wdcv(self, cmd: flex.Command) -> None:
        """``WDCV chnum,mode,start,stop,step`` on the MFCMU (PG PDF 549-550); a compliance is an error for it."""
        if len(cmd.args) == 6:
            raise flex.FlexError(flex.ERR_PARAMETER, "WDCV compliance is for an SMU sweep source only")
        for arg in cmd.args[2:4]:
            self._dc_value(arg, "WDCV")
        self._wdcv = self._sweep_source(cmd, -DC_MAX, DC_MAX, "WDCV")

    @handles("WFC")
    def _cmd_wfc(self, cmd: flex.Command) -> None:
        """``WFC chnum,mode,start,stop,step``: 1 kHz to 5 MHz (PG PDF 550-551)."""
        self._wfc = self._sweep_source(cmd, F_MIN, F_MAX, "WFC")

    @handles("WACV")
    def _cmd_wacv(self, cmd: flex.Command) -> None:
        """``WACV chnum,mode,start,stop,step``: 0 to 0.25 V rms (PG PDF 547)."""
        self._wacv = self._sweep_source(cmd, 0.0, AC_MAX, "WACV")

    @handles("WTDCV", "WTFC", "WTACV")
    def _cmd_cmu_timing(self, cmd: flex.Command) -> None:
        """``WTDCV``/``WTFC``/``WTACV hold,delay[,Sdelay[,Tdelay[,Mdelay]]]`` (PG PDF 565-568)."""
        flex.arity(cmd, 2, 5)
        values = [flex.number(a) for a in cmd.args] + [0.0] * (5 - len(cmd.args))
        hold, delay, sdelay, tdelay, mdelay = values
        if not (0 <= hold <= 655.35 and 0 <= delay <= TIMING_LIMITS[cmd.mnemonic] and 0 <= sdelay <= 1.0
                and 0 <= tdelay <= min(delay, 65.535) and 0 <= mdelay <= 65.535):
            raise flex.FlexError(flex.ERR_PARAMETER, cmd.text)
        self._cmu_timing[cmd.mnemonic] = (hold, delay, sdelay, tdelay, mdelay)

    @handles("WMDCV", "WMFC", "WMACV")
    def _cmd_cmu_abort(self, cmd: flex.Command) -> None:
        """``WMDCV``/``WMFC``/``WMACV abort[,post]``: abort 1 off / 2 on, post 1 start / 2 stop (PG PDF 553-556)."""
        flex.arity(cmd, 1, 2)
        abort = flex.integer(cmd.args[0])
        post = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if abort not in (1, 2) or post not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, cmd.text)
        self._cmu_abort[cmd.mnemonic] = (abort, post)

    @handles("PDCV")
    def _cmd_pdcv(self, cmd: flex.Command) -> None:
        """``PDCV chnum,base,pulse`` (PG PDF 484-485)."""
        flex.arity(cmd, 3, 3)
        channel, _ = self._cmu_enabled(cmd.args[0])
        self._pdcv = (channel, self._dc_value(cmd.args[1], "PDCV base"), self._dc_value(cmd.args[2], "PDCV pulse"))

    @handles("PTDCV")
    def _cmd_ptdcv(self, cmd: flex.Command) -> None:
        """``PTDCV hold,width[,period[,Tdelay]]`` (PG PDF 487-488)."""
        flex.arity(cmd, 2, 4)
        hold = self._value(cmd.args[0], 0.0, 655.35, "PTDCV hold")
        width = self._value(cmd.args[1], 0.008, 655.35, "PTDCV width")
        period = flex.number(cmd.args[2]) if len(cmd.args) > 2 else 0.0  # omitted: automatic, as 0 (PDF 488)
        gap = 2e-3 if width <= 0.1 else 10e-3
        if period != 0 and not (0.01 <= period <= 655.35 and period >= width + gap - 1e-12):
            raise flex.FlexError(flex.ERR_PARAMETER, f"PTDCV period {period}")
        tdelay = self._value(cmd.args[3], 0.0, width, "PTDCV Tdelay") if len(cmd.args) > 3 else 0.0
        self._ptdcv = (hold, width, period or width + gap, tdelay)

    @handles("PWDCV")
    def _cmd_pwdcv(self, cmd: flex.Command) -> None:
        """``PWDCV chnum,mode,base,start,stop,step``: linear modes 1/3 only (error 283; PG PDF 489-490)."""
        flex.arity(cmd, 6, 6)
        channel, _ = self._cmu_enabled(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode in (2, 4):
            raise flex.FlexError(flex.ERR_CV_PULSE_LINEAR)
        if mode not in (1, 3):
            raise flex.FlexError(flex.ERR_PARAMETER, f"PWDCV mode {mode}")
        base, start, stop = (self._dc_value(a, "PWDCV") for a in cmd.args[2:5])
        self._pwdcv = (channel, mode, base, start, stop, self._steps_arg(cmd.args[5]))

    @handles("MDCV")
    def _cmd_mdcv(self, cmd: flex.Command) -> None:
        """``MDCV chnum,base,bias[,post]``; without ``post`` the previous post value stays (PG PDF 467-468)."""
        flex.arity(cmd, 3, 4)
        channel, _ = self._cmu_enabled(cmd.args[0])
        base, bias = self._dc_value(cmd.args[1], "MDCV base"), self._dc_value(cmd.args[2], "MDCV bias")
        if len(cmd.args) > 3:
            self._mdcv_post = self._dc_value(cmd.args[3], "MDCV post")
        self._mdcv = (channel, base, bias)

    @handles("MTDCV")
    def _cmd_mtdcv(self, cmd: flex.Command) -> None:
        """``MTDCV h_bias,interval,number[,h_base]`` (PG PDF 476-477)."""
        flex.arity(cmd, 3, 4)
        h_bias = self._value(cmd.args[0], 0.0, 655.35, "MTDCV h_bias")
        interval = self._value(cmd.args[1], 0.008, 655.35, "MTDCV interval")
        number = flex.integer(cmd.args[2])
        if not 1 <= number <= 10001:
            raise flex.FlexError(flex.ERR_PARAMETER, f"MTDCV number {number}")
        h_base = self._value(cmd.args[3], 0.0, 655.35, "MTDCV h_base") if len(cmd.args) > 3 else 0.0
        self._mtdcv = (h_bias, interval, number, h_base)

    # -- phase compensation and data correction -------------------------------------------------------------------

    @handles("ADJ")
    def _cmd_adj(self, cmd: flex.Command) -> None:
        """``ADJ chnum,mode``: 0 auto, 1 manual, 2 load adaptive; initializes the MFCMU (PG PDF 355)."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ADJ mode {mode}")
        self._cmu_persistent(channel).adj_mode = mode
        self._initialize_cmu(channel)

    @handles("ADJ?")
    def _cmd_adj_q(self, cmd: flex.Command) -> str:
        """``ADJ? chnum[,mode]``: mode 0 returns the last result; mode 1 (also when omitted) measures the phase
        compensation (manual mode only, error 680; 30 s; initializes the MFCMU; the human has opened the terminals)
        and answers 0 (PG PDF 355-356)."""
        flex.arity(cmd, 1, 2)
        channel = self._cmu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 1
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"ADJ? mode {mode}")
        if mode == 1:
            if self._cmu_persistent(channel).adj_mode != 1:
                raise flex.FlexError(flex.ERR_ADJ_NOT_MANUAL)
            self.state.cmu_phase_results[channel] = 0
            self._initialize_cmu(channel)
            self._busy_until = self._now() + PHASE_COMPENSATION_S * self.faults.slow_factor()
        return str(self.state.cmu_phase_results.get(channel, PHASE_NOT_PERFORMED))

    @handles("CORRL")
    def _cmd_corrl(self, cmd: flex.Command) -> None:
        """``CORRL chnum,freq``: add a correction frequency; functions off, data cleared (PG PDF 384)."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        freq = self._value(cmd.args[1], F_MIN, F_MAX, "CORRL freq")
        self._corrections_off(channel, clear_data=True)
        freqs = self._cmu_persistent(channel).freqs
        if not any(math.isclose(freq, f, rel_tol=1e-9) for f in freqs):
            freqs.append(freq)

    @handles("CLCORR")
    def _cmd_clcorr(self, cmd: flex.Command) -> None:
        """``CLCORR chnum,mode``: functions off, data and list cleared; mode 2 loads the default list (PDF 379)."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        mode = flex.integer(cmd.args[1])
        if mode not in (1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER, f"CLCORR mode {mode}")
        self._corrections_off(channel, clear_data=True)
        self._cmu_persistent(channel).freqs = list(DEFAULT_FREQS) if mode == 2 else []

    @handles("CORRL?")
    def _cmd_corrl_q(self, cmd: flex.Command) -> str:
        """``CORRL? chnum[,index]``: the number of listed correction frequencies, or the frequency at ``index`` (1 =
        the first; error 120 outside the list) (PG PDF 385). Simulator convention (TODO(verify)[L6.A5, L6.A8]): the
        list keeps the order it was written in and frequencies are answered as plain decimals."""
        flex.arity(cmd, 1, 2)
        channel = self._cmu_channel(cmd.args[0])
        freqs = self._cmu_persistent(channel).freqs
        if len(cmd.args) == 1:
            return str(len(freqs))
        index = flex.integer(cmd.args[1])
        if not 1 <= index <= len(freqs):
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORRL? index {index} (list of {len(freqs)})")
        return format(freqs[index - 1], ".7g")

    @handles("DCORR?")
    def _cmd_dcorr_q(self, cmd: flex.Command) -> str:
        """``DCORR? chnum,corr``: ``mode,primary,secondary`` of the standard's reference value (PG PDF 389-390).
        Simulator convention (TODO(verify)[L6.A2, L6.A8]): a standard never set by ``DCORR`` answers the ideal value
        0, 0 in its mode (open 100, short and load 400)."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        corr = flex.integer(cmd.args[1])
        if corr not in CORRECTION_MODES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"DCORR? corr {corr}")
        mode, primary, secondary = self._cmu_persistent(channel).standards.get(corr, [DCORR_MODE[corr], 0.0, 0.0])
        return f"{int(mode)},{format(primary, '.7g')},{format(secondary, '.7g')}"

    @handles("DCORR")
    def _cmd_dcorr(self, cmd: flex.Command) -> None:
        """``DCORR chnum,corr,mode,primary,secondary``: the standard's reference (open 100 Cp-G, short/load 400 Ls-Rs;
        error 682 otherwise); functions off, data cleared (PG PDF 389)."""
        flex.arity(cmd, 5, 5)
        channel = self._cmu_channel(cmd.args[0])
        corr, mode = flex.integer(cmd.args[1]), flex.integer(cmd.args[2])
        if corr not in CORRECTION_MODES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"DCORR corr {corr}")
        if mode != DCORR_MODE[corr]:
            raise flex.FlexError(flex.ERR_CORR_STANDARD, f"DCORR mode {mode} for correction {corr}")
        primary, secondary = flex.number(cmd.args[3]), flex.number(cmd.args[4])
        self._corrections_off(channel, clear_data=True)
        self._cmu_persistent(channel).standards[corr] = [float(mode), primary, secondary]

    @handles("CORR?")
    def _cmd_corr_q(self, cmd: flex.Command) -> str:
        """``CORR? chnum,corr``: measure the standard at every listed frequency with the present AC level (error 684 at
        0 V rms; a load needs its ``DCORR`` reference, error 682); 0 completed, 1 failed (empty list) (PDF 382-383)."""
        flex.arity(cmd, 2, 2)
        channel, state = self._cmu_enabled(cmd.args[0])
        corr = flex.integer(cmd.args[1])
        if corr not in CORRECTION_MODES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORR? corr {corr}")
        if state.ac_vrms == 0:
            raise flex.FlexError(flex.ERR_CORR_AC_ZERO)
        persistent = self._cmu_persistent(channel)
        reference = persistent.standards.get(corr)
        if corr == 3 and reference is None:
            raise flex.FlexError(flex.ERR_CORR_STANDARD, "the load standard has no DCORR reference value")
        if not persistent.freqs:
            return "1"
        for freq in persistent.freqs:
            point = self._correction_point(channel, freq)
            if point is None:
                point = CmuCorrectionPoint(freq_hz=freq)
                persistent.data.append(point)
            z = self._standard_reading(channel, corr, freq, reference)
            value = [z.real, z.imag]
            if corr == 1:
                point.open = value
            elif corr == 2:
                point.short = value
            else:
                point.load = value
                ref = complex(reference[2], 2 * math.pi * freq * reference[1]) if reference else 0j
                point.load_ref = [ref.real, ref.imag]
        self._busy_until = self._now() + CORR_POINT_S * len(persistent.freqs) * self.faults.slow_factor()
        return "0"

    @handles("CORRDT")
    def _cmd_corrdt(self, cmd: flex.Command) -> None:
        """``CORRDT chnum,freq,open_r,open_i,short_r,short_i,load_r,load_i``: the data of one frequency (open as G, B;
        short and load as R, X), the frequency added to the list (PG PDF 383-384)."""
        flex.arity(cmd, 8, 8)
        channel = self._cmu_channel(cmd.args[0])
        freq = self._value(cmd.args[1], F_MIN, F_MAX, "CORRDT freq")
        og, ob, sr, sx, lr, lx = (flex.number(a) for a in cmd.args[2:])
        persistent = self._cmu_persistent(channel)
        if not any(math.isclose(freq, f, rel_tol=1e-9) for f in persistent.freqs):
            persistent.freqs.append(freq)
        point = self._correction_point(channel, freq)
        if point is None:
            point = CmuCorrectionPoint(freq_hz=freq)
            persistent.data.append(point)
        y_open = complex(og, ob)
        z_open = None if y_open == 0 else 1.0 / y_open
        point.open = None if z_open is None else [z_open.real, z_open.imag]
        point.short = [sr, sx]
        point.load = [lr, lx]
        reference = persistent.standards.get(3)
        if reference is not None:
            ref = complex(reference[2], 2 * math.pi * freq * reference[1])
            point.load_ref = [ref.real, ref.imag]

    @handles("CORRDT?")
    def _cmd_corrdt_q(self, cmd: flex.Command) -> str:
        """``CORRDT? chnum,index``: ``freq,open_r,open_i,short_r,short_i,load_r,load_i`` of the ``index``-th listed
        frequency (open as G, B; short and load as R, X; PG PDF 384; error 120 outside the list). Simulator
        convention: a correction never measured at that frequency answers 0, 0 (same fact as ``driver/cmu_data.py``
        ``CorrectionData``) and numbers are answered as plain decimals."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        freqs = self._cmu_persistent(channel).freqs
        index = flex.integer(cmd.args[1])
        if not 1 <= index <= len(freqs):
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORRDT? index {index} (list of {len(freqs)})")
        freq = freqs[index - 1]
        point = self._correction_point(channel, freq)
        y_open = 0j
        if point is not None and point.open is not None and complex(*point.open) != 0:
            y_open = 1.0 / complex(*point.open)
        short = point.short if point is not None and point.short is not None else [0.0, 0.0]
        load = point.load if point is not None and point.load is not None else [0.0, 0.0]
        values = (freq, y_open.real, y_open.imag, short[0], short[1], load[0], load[1])
        return ",".join(format(v, ".7g") for v in values)

    @handles("CORRST")
    def _cmd_corrst(self, cmd: flex.Command) -> None:
        """``CORRST chnum,corr,state``: ON needs data of that correction (error 685; PG PDF 387-388)."""
        flex.arity(cmd, 3, 3)
        channel = self._cmu_channel(cmd.args[0])
        corr, on = flex.integer(cmd.args[1]), flex.integer(cmd.args[2])
        if corr not in CORRECTION_MODES or on not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, cmd.text)
        attribute = {1: "open", 2: "short", 3: "load"}[corr]
        if on and not any(getattr(p, attribute) is not None for p in self._cmu_persistent(channel).data):
            raise flex.FlexError(flex.ERR_CORR_INCOMPLETE)
        self.state.cmu_corrections.setdefault(channel, {})[corr] = bool(on)

    @handles("CORRST?")
    def _cmd_corrst_q(self, cmd: flex.Command) -> str:
        """``CORRST? chnum,corr``: 1 when the correction function is ON, else 0 (PG PDF 388)."""
        flex.arity(cmd, 2, 2)
        channel = self._cmu_channel(cmd.args[0])
        corr = flex.integer(cmd.args[1])
        if corr not in CORRECTION_MODES:
            raise flex.FlexError(flex.ERR_PARAMETER, f"CORRST? correction mode {corr}")
        return "1" if self.state.cmu_corrections.get(channel, {}).get(corr, False) else "0"

    # -- learn query ----------------------------------------------------------------------------------------------

    @learns(70, 71, 72, 73, 90)
    def _lrn_cmu(self, kind: int) -> str:
        """``*LRN?`` 70 ``IMP``, 71 ``LMN``, 72 ``ACT``, 73 ``RC`` per MFCMU, 90 ``ADJ`` per MFCMU (PG PDF 452; written
        without a blank, like the simulator's type 31)."""
        if kind == 70:
            return f"IMP{self._imp}"
        if kind == 71:
            return f"LMN{1 if self._lmn else 0}"
        if kind == 72:
            return f"ACT{self._act[0]},{self._act[1]}"
        cmus = self._cmu_slots()
        if kind == 73:
            return ";".join(f"RC{c},{self._rc.get(c, (0, 0))[0]},{self._rc.get(c, (0, 0))[1]}" for c in cmus)
        return ";".join(f"ADJ{c},{self._cmu_persistent(c).adj_mode}" for c in cmus)

    # -- MM/XE dispatch by measurement mode -----------------------------------------------------------------------

    @handles("MM")
    def _cmd_mm_by_mode(self, cmd: flex.Command) -> None:
        """``MM mode,chnum...``: MFCMU modes 17-26 here (MM 18: the MFCMU first, then up to nine SMUs; the others one
        MFCMU), every other mode in ``SmuUnit._cmd_mm`` (PG PDF 470-472)."""
        if not cmd.args:
            raise flex.FlexError(flex.ERR_TERMINATOR)
        mode = flex.integer(cmd.args[0])
        if mode not in CMU_MODES:
            self._cmd_mm(cmd)
            return
        channels = cmd.args[1:]
        if not channels or (mode != 18 and len(channels) != 1) or len(channels) > 10:
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT)
        cmu = self._cmu_channel(channels[0])
        smus = [self._smu(a) for a in channels[1:]]
        if len(set(smus)) != len(smus) or set(smus) & self._scuu_modules():
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT if len(set(smus)) != len(smus) else flex.ERR_NOT_ALLOWED)
        self._mm = (mode, [cmu, *smus])

    @handles("XE")
    def _cmd_xe_by_mode(self, cmd: flex.Command) -> None:
        """``XE``: an MFCMU measurement mode is evaluated by ``CmuEngine``, every other by ``SmuUnit._cmd_xe``."""
        if self._mm is None or self._mm[0] not in CMU_MODES:
            self._cmd_xe(cmd)
            return
        flex.arity(cmd, 0, 0)
        mode, channels = self._mm
        for channel in channels:
            if not self.state.channels[channel].output_on:
                raise flex.FlexError(flex.ERR_OUTPUT_OFF, f"channel {channel}")
        steps, on_end, abort = self._cmu_plan(mode, channels[0])
        self._measurement = self._cmu_measure(mode, channels, steps, self._now(), on_end, abort)
        self._busy_until = self._measurement.end
        self.interrupt_pending = self.faults.interrupts_measurement()

    def _cmu_plan(self, mode: int, cmu: int) -> tuple[list[CmuStep], Callable[[bool, bool], None], bool]:
        """The steps of MFCMU measurement ``mode`` on ``cmu``, its end action (post values; error 320 trips the
        output) and whether the automatic abort is on (module docstring)."""
        state = self.state.channels[cmu]
        t = self._cmu_time()
        dc, ac, f = state.voltage, state.ac_vrms, state.freq_hz

        def finish(apply: Callable[[bool], None]) -> Callable[[bool, bool], None]:
            def end(aborted: bool, tripped: bool) -> None:
                if tripped:
                    self._cmu_off(cmu)
                elif self.state.channels[cmu].output_on:
                    apply(aborted)
            return end

        if mode == 17:
            return [CmuStep(dc, ac, f, None)], finish(lambda _ab: None), False
        if mode in (18, 22, 23):
            name, source = {18: ("WTDCV", self._wdcv), 22: ("WTFC", self._wfc), 23: ("WTACV", self._wacv)}[mode]
            if source is None or source[0] != cmu:
                raise flex.FlexError({18: flex.ERR_NO_CV_SWEEP, 22: flex.ERR_NO_CF_SWEEP}.get(mode, flex.ERR_PARAMETER))
            _, sweep_mode, start, stop, n = source
            values = _sweep_values(sweep_mode, start, stop, n)
            hold, delay, sdelay = self._cmu_timing[name][:3]
            period = delay + max(t, sdelay)
            steps = []
            for k, value in enumerate(values):
                signal = {18: (value, ac, f), 22: (dc, ac, value), 23: (dc, value, f)}[mode]
                previous = values[k - 1] if k else value
                before_dc = {18: previous, 22: dc, 23: dc}[mode]
                before = [(hold + delay, signal[0])] if k == 0 else [(period - delay - t, before_dc),
                                                                      (delay, signal[0])]
                steps.append(CmuStep(*signal, source=value, before=before, start_s=hold + k * period + delay,
                                     position=k))
            abort, post = self._cmu_abort[{18: "WMDCV", 22: "WMFC", 23: "WMACV"}[mode]]
            attribute = {18: "voltage", 22: "freq_hz", 23: "ac_vrms"}[mode]

            def apply_sweep(aborted: bool) -> None:
                setattr(self.state.channels[cmu], attribute, start if aborted or post == 1 else stop)
            return steps, finish(apply_sweep), abort == 2
        if mode in (19, 20):
            if mode == 19 and (self._pdcv is None or self._pdcv[0] != cmu):
                raise flex.FlexError(flex.ERR_NO_CV_PULSE)
            if mode == 20 and (self._pwdcv is None or self._pwdcv[0] != cmu):
                raise flex.FlexError(flex.ERR_NO_CV_PULSE_SWEEP)
            hold, width, period, _ = self._ptdcv
            if width < _pulse_min_width(f):
                raise flex.FlexError(flex.ERR_CMU_PULSE_WIDTH, f"width {width} s at {f} Hz")
            on = max(width - t, 0.0)
            if mode == 19 and self._pdcv is not None:
                _, base, pulse = self._pdcv
                step = CmuStep(pulse, ac, f, None, before=[(hold, base), (on, pulse)], start_s=hold + on)
                return [step], finish(lambda _ab: setattr(self.state.channels[cmu], "voltage", base)), False
            assert self._pwdcv is not None
            _, pw_mode, base, start, stop, n = self._pwdcv
            peaks = _sweep_values(pw_mode, start, stop, n)
            steps = [CmuStep(peak, ac, f, peak, before=[(hold if k == 0 else period - width, base), (on, peak)],
                             start_s=hold + k * period + on, position=k) for k, peak in enumerate(peaks)]
            abort = self._cmu_abort["WMDCV"][0]
            return steps, finish(lambda _ab: setattr(self.state.channels[cmu], "voltage", base)), abort == 2
        if self._mdcv is None or self._mdcv[0] != cmu:
            raise flex.FlexError(flex.ERR_PARAMETER, "MM 26 needs MDCV")
        _, base, bias = self._mdcv
        h_bias, interval, number, h_base = self._mtdcv
        skip = max(1, math.ceil(t / interval - 1e-9))
        steps = []
        for k in range(number):
            index = 1 + k * skip
            start_s = h_base + h_bias + (index - 1) * interval
            before = [(h_base, base), (h_bias, bias)] if k == 0 else [(start_s - steps[-1].start_s - t, bias)]
            steps.append(CmuStep(bias, ac, f, None, before=before, start_s=start_s, position=k, index=index))
        post = self._mdcv_post

        def apply_ct(aborted: bool) -> None:
            self.state.channels[cmu].voltage = base if aborted else post
        return steps, finish(apply_ct), False

    # -- SCUU modules (answered by the switch unit) ----------------------------------------------------------------

    def _scuu_modules(self) -> set[int]:
        """Channels of the SCUUs' modules: each SCUU's MFCMU and its two SMUs (PG PDF 520)."""
        found: set[int] = set()
        for cmu in self._cmu_slots():
            if self._scuu_on(cmu):
                found |= {cmu, cmu - 1, cmu - 2}
        return found

