"""Core unit of the simulator: identity and status, buffer and format, output switches, ``AB``, A/D converters,
auto-calibration (``CM``) and the learn query (``*LRN?``).

``CoreUnit`` is a mixin of ``SimInstrument`` (``transport/sim/instrument.py``): its ``@handles`` methods are the FLEX
handlers of the family-independent v1 subset, registered by mnemonic; it uses the dispatcher's shared state and
helpers (``state``, ``faults``, ``_channel``, ``_smu``, ``_queue_error``, ``_status_byte``, ``_on_levels``, the
measurement lifecycle). Manual references (Programming Guide Ed. 15, physical PDF pages): ``*IDN?`` 440; ``UNT?``
545; ``ERRX?`` 431-432; ``*STB?`` 523; ``*OPC?`` 480; ``*RST`` 502 (initialise like power-on, PDF 175); ``LOP?``
446-447 (Table 4-26); ``*TST?`` 540-541; ``*CAL?`` 377; ``NUB?`` 478; ``FMT`` 436-438; ``BC`` 364; ``TSC`` 538-539;
``CN`` 380-381; ``CL`` 378; ``DZ`` 397; ``AB`` 351-352; ``AAD`` 351; ``AIT`` 356-359; ``AV`` 362-363; ``CM`` 379
(printed 4-61); ``*LRN?`` 447-450 (printed 4-129 to 4-132; types 0 and 31 are simulated, other types are logged
``unsupported``). The simulator does not run the auto-calibration itself (it only keeps the ``CM`` switch).
"""

from __future__ import annotations

import math
from typing import ClassVar

from b1500_test_agent.models.station import SMU_TYPES
from b1500_test_agent.transport.sim import flex
from b1500_test_agent.transport.sim.state import ChannelState
from b1500_test_agent.transport.sim.units.base import CMU_TYPES, DEFAULT_ICOMP, SPGU_TYPES, Unsupported, handles

NOISE_MULTIPLIERS = ((0.25, 3.0), (4.0, 1.0), (math.inf, 0.3))
"""(integration time in PLC below which, noise multiplier): short 3x, medium 1x, long 0.3x (blueprint 4)."""


class CoreUnit:
    """Family-independent FLEX handlers of ``SimInstrument`` (see the module docstring)."""

    def _reset_core_settings(self) -> None:
        """Data format, time stamp and A/D converter setup to their initial settings (PG Table 2-13, PDF 180)."""
        self._fmt = 1
        self._fmt_mode = 0
        self._tsc = False
        self._adc: dict[int, int] = {}
        self._ait: dict[int, tuple[int, float]] = {0: (0, 1), 1: (0, 6), 2: (2, 1)}

    def _switchable(self) -> frozenset[str]:
        return SMU_TYPES | CMU_TYPES | SPGU_TYPES

    def _channels_arg(self, cmd: flex.Command) -> list[int]:
        if len(cmd.args) > 15:
            raise flex.FlexError(flex.ERR_CHANNEL_COUNT, f"{len(cmd.args)} channels")
        if cmd.args:
            return [self._channel(a, kinds=self._switchable()) for a in cmd.args]
        return [ch for ch in self.installed_channels() if self._channel_type(ch) in self._switchable()]

    # -- identity and status -------------------------------------------------------------------------------------------

    @handles("*IDN?")
    def _cmd_idn(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return self.faults.idn() or self.scenario.idn

    @handles("UNT?")
    def _cmd_unt(self, cmd: flex.Command) -> str:
        """``UNT?``: ``model,revision`` per slot 1-10 (``0,0`` when empty), ``;``-separated (PG PDF 545)."""
        flex.arity(cmd, 0, 1)
        mode = flex.integer(cmd.args[0]) if cmd.args else 0
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        slots = self._slots()
        entries = [f"{slots[s].model},{slots[s].revision}" if s in slots else "0,0" for s in range(1, 11)]
        if mode == 1:
            entries.insert(0, "B1500A,0")
        return ";".join(entries)

    @handles("ERRX?")
    def _cmd_errx(self, cmd: flex.Command) -> str:
        """``ERRX?``: ``code,"message"`` or ``0,"No Error."``; mode 1 = code only (PG PDF 431-432)."""
        flex.arity(cmd, 0, 1)
        mode = flex.integer(cmd.args[0]) if cmd.args else 0
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._error_flag = False
        code = self._errors.popleft() if self._errors else 0
        if mode == 1:
            return str(code)
        return f'{code},"{flex.error_message(code) if code else "No Error."}"'

    @handles("*STB?")
    def _cmd_stb(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return str(self._status_byte(busy=False))

    @handles("*OPC?")
    def _cmd_opc(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return "1"

    @handles("*RST")
    def _cmd_rst(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 0, 0)
        self._initialize()

    @handles("LOP?")
    def _cmd_lop(self, cmd: flex.Command) -> str:
        """``LOP?``: ``LOP`` + ten two-digit slot codes (Table 4-26, PDF 446-447).

        The response is written as in the manual's example ``LOP00,11,00,...`` (PDF 447; the syntax line on PDF 446
        shows a blank after ``LOP``). SMU: 00 off, 01 forcing voltage, 02/03 forcing positive/negative current, 11
        voltage compliance, 12/13 positive/negative current compliance; MFCMU on: 40; HVSPGU/WGFMU: 00 (Table 4-26
        has no code for them).
        """
        flex.arity(cmd, 0, 0)
        forced = self._on_currents()
        clamped: set[int] | None = None
        if forced:
            _, currents, clamped = self.dc_solution()
        else:  # voltage sources only: compliance where the programmed levels would drive more than Icomp (v1)
            currents = self._current(self._on_levels())
        codes = []
        for slot in range(1, 11):
            module = self._module_type(slot)
            state = self.state.channels.get(slot)
            if module is None or state is None or not state.output_on:
                codes.append("00")
            elif module in SMU_TYPES and slot in forced:
                codes.append("11" if slot in clamped else ("02" if forced[slot][0] >= 0 else "03"))
            elif module in SMU_TYPES:
                current = currents.get(slot, 0.0)
                limit = state.icomp if state.icomp is not None else DEFAULT_ICOMP
                in_compliance = slot in clamped if clamped is not None else abs(current) > limit * (1 + 1e-9)
                codes.append(("12" if current > 0 else "13") if in_compliance else "01")
            elif module in CMU_TYPES:
                codes.append("40")
            else:
                codes.append("00")
        return "LOP" + ",".join(codes)

    def _selftest_slot(self, arg: str) -> None:
        slot = flex.integer(arg)
        if not 0 <= slot <= 11:
            raise flex.FlexError(flex.ERR_PARAMETER, f"slot {slot}")
        if 1 <= slot <= 10 and slot not in self._slots():
            raise flex.FlexError(flex.ERR_NO_MODULE, f"slot {slot}")

    def _selftest(self) -> str:
        if self._high_voltage(self._on_levels()):
            raise flex.FlexError(flex.ERR_HV_SELFTEST)
        self._error_flag = False
        for channel in list(self.state.channels):
            self._close_channel(channel)
        return "0"

    @handles("*TST?")
    def _cmd_tst(self, cmd: flex.Command) -> str:
        """``*TST?``: self-test + self-calibration; always passes (0); leaves modules as after ``CL`` (PDF 540)."""
        flex.arity(cmd, 0, 2)
        if cmd.args:
            self._selftest_slot(cmd.args[0])
        if len(cmd.args) > 1 and flex.integer(cmd.args[1]) not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        return self._selftest()

    @handles("*CAL?")
    def _cmd_cal(self, cmd: flex.Command) -> str:
        """``*CAL?``: self-calibration; always passes (0) (PDF 377)."""
        flex.arity(cmd, 0, 1)
        if cmd.args:
            self._selftest_slot(cmd.args[0])
        return self._selftest()

    @handles("NUB?")
    def _cmd_nub(self, cmd: flex.Command) -> str:
        flex.arity(cmd, 0, 0)
        return str(len(self._buffer))

    # -- buffer and format ---------------------------------------------------------------------------------------------

    def _clear_buffers(self) -> None:
        self._buffer = []
        self._queries.clear()

    @handles("FMT")
    def _cmd_fmt(self, cmd: flex.Command) -> None:
        """``FMT format[,mode]``: only ASCII 1 and 5, modes 0 and 1 (PDF 436-438); clears the output buffer."""
        flex.arity(cmd, 1, 2)
        fmt = flex.integer(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 0
        if fmt not in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, 25) or not 0 <= mode <= 10:
            raise flex.FlexError(flex.ERR_PARAMETER)
        if fmt not in (1, 5):
            raise Unsupported(f"FMT {fmt}")
        if mode not in (0, 1):
            raise Unsupported(f"FMT mode {mode}")
        self._fmt, self._fmt_mode = fmt, mode
        self._clear_buffers()

    @handles("BC")
    def _cmd_bc(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 0, 0)
        self._clear_buffers()

    @handles("TSC")
    def _cmd_tsc(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._tsc = mode == 1

    # -- channels ------------------------------------------------------------------------------------------------------

    def _close_channel(self, channel: int) -> None:
        """``CL`` condition: switch off, 0 V, 100 uA compliance (PDF 378), unless the output is stuck."""
        if not self.faults.stuck(channel):
            self.state.channels[channel] = ChannelState(icomp=None)

    @handles("CN")
    def _cmd_cn(self, cmd: flex.Command) -> None:
        for channel in self._channels_arg(cmd):
            state = self.state.channels[channel]
            if not state.output_on:
                self.state.channels[channel] = ChannelState(output_on=True, voltage=0.0, icomp=DEFAULT_ICOMP)

    @handles("CL")
    def _cmd_cl(self, cmd: flex.Command) -> None:
        for channel in self._channels_arg(cmd):
            self._close_channel(channel)

    @handles("DZ")
    def _cmd_dz(self, cmd: flex.Command) -> None:
        """``DZ``: 0 V on the channels (all with the switch on by default); the switch stays on (PDF 397)."""
        for channel in self._channels_arg(cmd):
            state = self.state.channels[channel]
            if state.output_on and not self.faults.stuck(channel):
                state.mode, state.voltage, state.current = "V", 0.0, 0.0  # a current source becomes a 0 V source
                if state.icomp is None or state.icomp > DEFAULT_ICOMP:
                    state.icomp = DEFAULT_ICOMP

    @handles("AB")
    def _cmd_ab(self, cmd: flex.Command) -> None:
        """``AB``: abort a running measurement; data measured so far stays, sweep sources go to the start value
        (PDF 351-352). Without a running measurement nothing changes; the ``abort_ignored`` fault makes it a no-op."""
        flex.arity(cmd, 0, 0)
        if self.faults.abort_ignored():
            return
        measurement = self._measurement
        if measurement is None:
            return
        if self.clock >= measurement.end:
            self._finish(measurement)
            return
        done = [block for block, end in zip(measurement.blocks, measurement.step_ends, strict=True)
                if end <= self.clock]
        for block in done:
            self._buffer.extend(block)
        self._rollback_devices(measurement)
        self._apply_end(measurement, aborted=True, at=self.clock)
        self._busy_until = self.clock

    # -- auto-calibration and learn query ------------------------------------------------------------------------------

    @handles("CM")
    def _cmd_cm(self, cmd: flex.Command) -> None:
        """``CM mode``: auto-calibration 0 OFF (initial setting) or 1 ON (PG p379 (4-61)); persistent state."""
        flex.arity(cmd, 1, 1)
        mode = flex.integer(cmd.args[0])
        if mode not in (0, 1):
            raise flex.FlexError(flex.ERR_PARAMETER, f"CM {mode}")
        self.state.auto_calibration = mode == 1

    def _lrn_settings(self) -> str:
        """``*LRN? 31``: ``TM...;AV...;CM...;FMT...[;MM...]`` (PG p448 (4-130)). The trigger mode is not simulated
        and reads its initial setting 1; ``AV`` mirrors the high-speed ADC setup (``AV -n`` for PLC mode)."""
        mode, n = self._ait[0]
        if mode == 2:
            av = f"AV{-int(n)}"
        elif mode in (0, 1):
            av = f"AV{int(n)},{mode}"
        else:
            av = "AV1,0"  # time mode has no AV form
        parts = ["TM1", av, f"CM{1 if self.state.auto_calibration else 0}", f"FMT{self._fmt},{self._fmt_mode}"]
        mm = getattr(self, "_mm", None)
        if mm is not None:
            mm_mode, channels = mm
            parts.append("MM" + ",".join(str(v) for v in (mm_mode, *channels)))
        return ";".join(parts)

    @handles("*LRN?")
    def _cmd_lrn(self, cmd: flex.Command) -> str:
        """``*LRN? type`` (PG p447-450 (4-129 to 4-132)): type 0 = output switches (``CN ch,...`` or ``CL``), type 31
        = ``TM``/``AV``/``CM``/``FMT``/``MM`` settings; any other type is not simulated (error 100, unsupported)."""
        flex.arity(cmd, 1, 1)
        kind = flex.integer(cmd.args[0])
        if not 0 <= kind <= 110:
            raise flex.FlexError(flex.ERR_PARAMETER, f"*LRN? {kind}")
        if kind == 0:
            on = [ch for ch, state in sorted(self.state.channels.items()) if state.output_on]
            return "CN" + ",".join(str(ch) for ch in on) if on else "CL"
        if kind == 31:
            return self._lrn_settings()
        raise Unsupported(f"*LRN? {kind} is not simulated (types 0 and 31 are)")

    # -- A/D converters ------------------------------------------------------------------------------------------------

    @handles("AAD")
    def _cmd_aad(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 2)
        channel = self._smu(cmd.args[0])
        adc = flex.integer(cmd.args[1])
        if adc not in (0, 1, 2):
            raise flex.FlexError(flex.ERR_PARAMETER)
        if adc != 2:  # the pulsed-measurement ADC is never used for DC measurements (PDF 351)
            self._adc[channel] = adc

    _AIT_LIMITS: ClassVar[dict[tuple[int, int], tuple[float, float, float]]] = {
        (0, 0): (1, 1023, 1), (0, 1): (1, 1023, 1), (0, 2): (1, 100, 1), (0, 3): (2e-6, 0.02, 2e-6),
        (1, 0): (1, 127, 6), (1, 1): (1, 127, 3), (1, 2): (1, 100, 1),
        (2, 2): (1, 100, 1), (2, 3): (2e-6, 0.02, 2e-6),
    }  # fmt: skip
    """(type, mode) → (min N, max N, default N) per Table 4-21 (PDF 358-359)."""

    @handles("AIT")
    def _cmd_ait(self, cmd: flex.Command) -> None:
        flex.arity(cmd, 2, 3)
        adc, mode = flex.integer(cmd.args[0]), flex.integer(cmd.args[1])
        limits = self._AIT_LIMITS.get((adc, mode))
        if limits is None:
            raise flex.FlexError(flex.ERR_PARAMETER, f"AIT type {adc} mode {mode}")
        low, high, default = limits
        n = (flex.number(cmd.args[2]) if mode == 3 else flex.integer(cmd.args[2])) if len(cmd.args) > 2 else default
        if not low <= n <= high:
            raise flex.FlexError(flex.ERR_PARAMETER, f"AIT N {n}")
        self._ait[adc] = (mode, n)

    @handles("AV")
    def _cmd_av(self, cmd: flex.Command) -> None:
        """``AV number[,mode]``: high-speed ADC averaging, same as ``AIT 0,...`` (PDF 362)."""
        flex.arity(cmd, 1, 2)
        number = flex.integer(cmd.args[0])
        mode = flex.integer(cmd.args[1]) if len(cmd.args) > 1 else 0
        if mode not in (0, 1) or not (1 <= number <= 1023 or -100 <= number <= -1):
            raise flex.FlexError(flex.ERR_PARAMETER)
        self._ait[0] = (2, -number) if number < 0 else (mode, number)

    def integration_time(self, channel: int) -> float:
        """Nominal time (s) of one measurement on ``channel`` from ``AAD``/``AIT``/``AV`` (Table 4-21)."""
        adc = self._adc.get(channel, 0)
        mode, n = self._ait[adc]
        plc = 1.0 / flex.LINE_FREQUENCY_HZ
        if adc == 1:
            if mode == 0:
                return n * flex.HR_AUTO_UNIT_S
            if mode == 1:
                return n * flex.HR_MANUAL_UNIT_S
            return n * plc
        if mode == 3:
            return float(n)
        samples = n * flex.SAMPLES_PER_PLC if mode == 2 else n
        return samples * plc / flex.SAMPLES_PER_PLC

    def noise_multiplier(self, channel: int) -> float:
        """Noise multiplier of ``channel``: 3x below 0.25 PLC, 1x below 4 PLC, else 0.3x (blueprint 4)."""
        plcs = self.integration_time(channel) * flex.LINE_FREQUENCY_HZ
        return next(mult for limit, mult in NOISE_MULTIPLIERS if plcs < limit)
