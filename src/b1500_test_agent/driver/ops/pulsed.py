"""SMU pulsed operations (``MM 3``, ``4``, ``5``, ``27``, ``28``): the pulsed setup model and its guarded writes
(blueprint v2 2.5, 2.7 kind ``smu_pulsed``).

``PulsedOps`` is a mixin of ``B1500Driver``. ``pulsed_setup`` checks every source before the first byte is written:
each pulse source with ``OutputGuard.check`` at its base and every peak/sweep level against its compliance, and with
``OutputGuard.check_pulse`` for the train one ``XE`` starts (width, period, pulses per trigger, the extreme level);
every staircase (``WV``/``WI``/``WNX``) and synchronous (``WSV``/``WSI``) source with ``check`` at both end points.
A current pulse source (``PI``/``PWI``, mode 2 of ``MCPNX``/``MCPWNX``) is checked by ``check_pulse`` at its voltage
compliance, the most the DUT can see during the pulse. ``pulsed_update`` re-programs only the pulse sources between
two triggers (a host list of pulse levels), guarded the same way. Command texts come from ``driver/flex/pulsed.py``,
``driver/flex/smu.py`` and ``driver/flex/core.py``; ``XE`` and the data read are ``CoreOps.execute_and_read``.

Setup order (PG examples Tables 3-4, 3-8, 3-9, 3-14, 3-15, PDF 196, 210, 214, 230, 234; the order of setting commands
before ``XE`` is free): ``AIT 2,3,<meas_time>`` (pulsed ADC), then

- MM 3: ``MM 3,ch``, ``CMM``, ``PT``, ``PV``/``PI``;
- MM 4: ``MM 4,ch``, ``CMM``, ``PT``, ``PWV``/``PWI``, ``WSV``/``WSI`` (after the pulsed sweep, which clears it),
  ``WM``;
- MM 5: ``MM 5,ch``, ``CMM``, ``PT``, ``WV``/``WI``, ``WSV``/``WSI``, ``PV``/``PI``, ``WM`` (``WT`` is not effective for
  pulsed measurements, PDF 565, so it is not sent);
- MM 27: ``MCPT``, ``MCPNT`` per pulse channel, ``MCPNX`` per pulse source, ``MM 27,chs``, ``CMM``;
- MM 28: ``MCPT``, ``MCPNT`` per pulse channel, ``MCPWS``, ``MCPWNX``/``MCPNX`` per pulse source, ``WNX`` per
  staircase source, ``MM 28,chs``, ``CMM``, ``WM``.

Source numbers ``N`` of MM 27/28: the pulsed sweep sources 1, 2, ..., then the ``WNX`` staircase sources, then the
pulsed bias sources (each group in setup order), so the first sweeping source is always N = 1 and its value per step
comes with ``FMT 1,1``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.driver.ops.smu import CmmMode, SweepSource
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel

PulsedMode = Literal[3, 4, 5, 27, 28]

SINGLE_CHANNEL_MODES = frozenset({flex.PULSED_SPOT_MODE, flex.PULSED_SWEEP_MODE, flex.PULSED_BIAS_SWEEP_MODE})
"""MM 3, 4, 5: one pulse source and one measurement channel (PG PDF 93, 98, 100)."""

MULTI_CHANNEL_MODES = frozenset({flex.MULTI_PULSED_SPOT_MODE, flex.MULTI_PULSED_SWEEP_MODE})
"""MM 27, 28: up to ten pulse/sweep sources and measurement channels (PG PDF 94, 104)."""

SWEEP_MODES = frozenset({flex.PULSED_SWEEP_MODE, flex.PULSED_BIAS_SWEEP_MODE, flex.MULTI_PULSED_SWEEP_MODE})
"""The pulsed modes with sweep steps (``WM`` abort applies)."""


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


class PulseSource(StrictModel):
    """One SMU pulse source: a pulsed bias (``peak``: ``PV``/``PI``, ``MCPNX``) or a pulsed sweep (``start``/``stop``:
    ``PWV``/``PWI``, ``MCPWNX``) from ``base``.

    ``source`` is what it forces (``V`` volts with Icomp ``comp`` in A, or ``I`` amperes with Vcomp ``comp`` in V; a
    current pulse keeps one polarity), ``range`` the output ranging code (Table 4-4/4-5; 0 auto), ``width`` its pulse
    width (``PT``; ``MCPNT`` in MM 27/28) and ``delay`` its ``MCPNT`` delay (MM 27/28; 0 on HR/MP/HPSMU).
    """

    channel: Channel
    source: Literal["V", "I"] = "V"
    base: float = 0.0
    peak: float | None = None
    start: float | None = None
    stop: float | None = None
    comp: float
    range: int = 0
    width: float = Field(gt=0)
    delay: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> PulseSource:
        if (self.peak is None) == (self.start is None or self.stop is None):
            raise ValueError("a pulse source has either peak (pulsed bias) or start and stop (pulsed sweep).")
        if self.peak is not None and (self.start is not None or self.stop is not None):
            raise ValueError("a pulsed bias (peak) takes no start/stop.")
        if self.comp == 0:
            raise ValueError("comp must be non-zero.")
        codes = flex.V_RANGE_CODES if self.source == "V" else flex.I_OUTPUT_RANGE_CODES
        if self.range not in codes:
            raise ValueError(f"range {self.range} is not an output ranging code of a {self.source} source.")
        levels = self.levels()
        if self.source == "I" and any(v > 0 for v in levels) and any(v < 0 for v in levels):
            raise ValueError("a current pulse source keeps one polarity (base, peak/start/stop).")
        return self

    @property
    def sweeping(self) -> bool:
        """True for a pulsed sweep (``start``/``stop``)."""
        return self.peak is None

    def levels(self) -> list[float]:
        """``[base, peak]`` or ``[base, start, stop]``."""
        if self.peak is not None:
            return [self.base, self.peak]
        assert self.start is not None and self.stop is not None
        return [self.base, self.start, self.stop]

    @property
    def extreme(self) -> float:
        """The pulse level with the largest magnitude (``peak``, or ``start``/``stop``), sign kept."""
        tops = self.levels()[1:]
        return max(tops, key=abs)

    def with_peak(self, peak: float) -> PulseSource:
        """This pulsed bias at another ``peak`` (a host list of pulse levels)."""
        if self.sweeping:
            raise ValueError("with_peak applies to a pulsed bias, not a pulsed sweep.")
        return self.model_copy(update={"peak": peak})


class PulsedSetup(StrictModel):
    """One pulsed measurement (``MM 3/4/5/27/28``; module docstring for the command order).

    ``mode``: the ``MM`` mode. ``measure``: measurement channels (MM 3/4/5: exactly one; 27/28: one to ten, measured in
    parallel, data in this order) with ``operation`` their ``CMM`` modes. ``hold``/``period``: ``PT``/``MCPT`` hold and
    period; ``meas_time``: the pulsed ADC's measurement time (``AIT 2,3``; it ends at the pulse end, so it is at most
    the width). ``pulses``: the pulse sources (MM 3/5: one pulsed bias; MM 4: one pulsed sweep; MM 27: pulsed biases;
    MM 28: pulsed sweeps and biases). ``staircase``: the ``WV``/``WI`` primary of MM 5; ``sync``: the synchronous
    ``WSV``/``WSI`` source of MM 4/5 (same output mode as the primary sweep); ``wnx``: the staircase sources of MM 28.
    ``points``, ``sweep`` (linear/log) and ``double``: the steps of every sweep source (``PWV``/``PWI``, ``WV``/``WI``,
    ``MCPWS``). ``average``: ``MCPT`` averaging (MM 27/28). ``auto_abort``/``post``: ``WM`` of the sweep modes.
    """

    mode: PulsedMode
    measure: tuple[Channel, ...] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    operation: dict[Channel, CmmMode] = Field(default_factory=dict)
    hold: float = Field(default=0.0, ge=0)
    period: float = Field(gt=0)
    meas_time: float = Field(gt=0)
    pulses: tuple[PulseSource, ...] = Field(min_length=1, max_length=flex.MCP_MAX_SOURCE)
    staircase: SweepSource | None = None
    sync: SweepSource | None = None
    wnx: tuple[SweepSource, ...] = Field(default=(), max_length=flex.MCP_MAX_SOURCE - 1)
    points: int = Field(default=1, ge=1, le=flex.MAX_SWEEP_STEPS)
    sweep: Literal["linear", "log"] = "linear"
    double: bool = False
    average: int = Field(default=1, ge=1, le=flex.MCPT_MAX_AVERAGE)
    auto_abort: bool = True
    post: Literal["start", "stop"] = "start"

    @model_validator(mode="after")
    def _consistent(self) -> PulsedSetup:
        single = self.mode in SINGLE_CHANNEL_MODES
        if single and (len(self.measure) != 1 or len(self.pulses) != 1):
            raise ValueError(f"mode {self.mode} takes one pulse source and one measurement channel.")
        if len({_norm(ch) for ch in self.measure}) != len(self.measure):
            raise ValueError("A measurement channel is listed twice.")
        if not set(self.operation) <= set(self.measure):
            raise ValueError("operation names a channel that is not measured.")
        sweeping = [p for p in self.pulses if p.sweeping]
        if self.mode in (flex.PULSED_SPOT_MODE, flex.PULSED_BIAS_SWEEP_MODE, flex.MULTI_PULSED_SPOT_MODE) and sweeping:
            raise ValueError(f"mode {self.mode} takes pulsed biases (peak), not pulsed sweeps.")
        if self.mode == flex.PULSED_SWEEP_MODE and not sweeping:
            raise ValueError("mode 4 needs a pulsed sweep source (start/stop).")
        if (self.staircase is not None) != (self.mode == flex.PULSED_BIAS_SWEEP_MODE):
            raise ValueError("the WV/WI staircase belongs to mode 5 and mode 5 needs it.")
        if self.sync is not None:
            if self.mode not in (flex.PULSED_SWEEP_MODE, flex.PULSED_BIAS_SWEEP_MODE):
                raise ValueError("a synchronous WSV/WSI source belongs to mode 4 or mode 5.")
            if self.sync.source != self.primary_source:
                raise ValueError("the synchronous source must use the primary sweep's output mode (PG PDF 99, 101).")
        if self.wnx and self.mode != flex.MULTI_PULSED_SWEEP_MODE:
            raise ValueError("WNX staircase sources belong to mode 28.")
        if self.mode == flex.MULTI_PULSED_SWEEP_MODE and not sweeping and not self.wnx:
            raise ValueError("mode 28 needs a pulsed sweep (MCPWNX) or a staircase (WNX) source.")
        if self.mode in (flex.PULSED_SWEEP_MODE, flex.PULSED_BIAS_SWEEP_MODE) and self.sweep != "linear":
            raise ValueError(f"mode {self.mode} sweeps linearly only (error 226, PG PDF 579).")
        if self.mode not in SWEEP_MODES and (self.points != 1 or self.double):
            raise ValueError(f"mode {self.mode} has no sweep steps (points 1, single).")
        if len(self.pulses) + len(self.wnx) > flex.MCP_MAX_SOURCE:
            raise ValueError(f"at most {flex.MCP_MAX_SOURCE} sources in mode 27/28.")
        channels = [p.channel for p in self.pulses] + [s.channel for s in self.followers]
        if len({_norm(ch) for ch in channels}) != len(channels):
            raise ValueError("a source channel is listed twice.")
        if self.average != 1 and self.mode not in MULTI_CHANNEL_MODES:
            raise ValueError("average (MCPT) belongs to mode 27/28.")
        if self.meas_time > min(p.width for p in self.pulses) + 1e-12:
            raise ValueError("the measurement time must fit inside the pulse width (it ends with the pulse).")
        if self.sweep == "log":
            for levels in self.sweep_levels():
                if levels[0] == 0 or levels[1] == 0 or (levels[0] > 0) != (levels[1] > 0):
                    raise ValueError("a log sweep needs non-zero start and stop of the same polarity on every source.")
        return self

    # -- derived -----------------------------------------------------------------------------------------------------

    @property
    def followers(self) -> list[SweepSource]:
        """The staircase-type sources: the MM 5 primary, the synchronous source, the MM 28 ``WNX`` sources."""
        out = [self.staircase] if self.staircase is not None else []
        if self.sync is not None:
            out.append(self.sync)
        return out + list(self.wnx)

    @property
    def primary_source(self) -> Literal["V", "I"]:
        """Output mode of the primary sweep: the MM 5 staircase, else the (first) pulsed sweep."""
        if self.staircase is not None:
            return self.staircase.source
        sweeping = [p for p in self.pulses if p.sweeping]
        return sweeping[0].source if sweeping else self.pulses[0].source

    def sweep_levels(self) -> list[tuple[float, float]]:
        """``(start, stop)`` of every sweeping source (pulsed sweeps, staircases, synchronous, ``WNX``)."""
        out = [(p.start, p.stop) for p in self.pulses if p.sweeping]
        return [(float(a), float(b)) for a, b in out if a is not None and b is not None] + [
            (s.start, s.stop) for s in self.followers]

    @property
    def wv_mode(self) -> int:
        """Sweep mode code (``PWV``/``WV``/``MCPWS``): 1 linear, 2 log, 3 linear double, 4 log double."""
        return (1 if self.sweep == "linear" else 2) + (2 if self.double else 0)

    @property
    def steps(self) -> int:
        """Sweep steps of one trigger (``2 x points`` for a double sweep; 1 for the spot modes)."""
        return self.points * (2 if self.double else 1)

    @property
    def pulses_per_trigger(self) -> int:
        """Pulses each pulse source outputs per ``XE``: one per step (times ``average`` in MM 27/28)."""
        return self.steps * self.average

    @property
    def width(self) -> float:
        """The longest pulse width (``PT`` width of MM 3/4/5)."""
        return max(p.width for p in self.pulses)

    @property
    def t0(self) -> float:
        """Longest delay + width (the ``MCPT`` period rule, PG PDF 464)."""
        return max(p.delay + p.width for p in self.pulses)

    def source_number(self, channel: int) -> int:
        """``N`` of the MM 27/28 source on ``channel`` (pulsed sweeps, then ``WNX``, then pulsed biases)."""
        channels = ([p.channel for p in self.pulses if p.sweeping] + [s.channel for s in self.wnx]
                    + [p.channel for p in self.pulses if not p.sweeping])
        for n, own in enumerate(channels, start=1):
            if _norm(own) == _norm(channel):
                return n
        raise ValueError(f"channel {channel} is no source of this setup")

    @property
    def returned_source(self) -> int | None:
        """The channel whose source value each step returns (``FMT x,1``/``FMT x,N``): MM 4 the pulsed sweep, MM 5
        the staircase primary, MM 28 the first pulsed sweep (else the first ``WNX``); ``None`` for MM 3/27."""
        if self.mode == flex.PULSED_SWEEP_MODE:
            return self.pulses[0].channel
        if self.mode == flex.PULSED_BIAS_SWEEP_MODE:
            assert self.staircase is not None
            return self.staircase.channel
        if self.mode == flex.MULTI_PULSED_SWEEP_MODE:
            sweeping = [p.channel for p in self.pulses if p.sweeping]
            return sweeping[0] if sweeping else self.wnx[0].channel
        return None

    @property
    def format_mode(self) -> int:
        """``FMT`` mode: 0 (MM 3/27) or 1 (MM 4/5: the primary sweep source; MM 28: source N = 1, the first sweeping
        one)."""
        return 0 if self.returned_source is None else 1

    # -- commands ----------------------------------------------------------------------------------------------------

    def pulse_command(self, pulse: PulseSource) -> str:
        """The ``PV``/``PI``/``PWV``/``PWI`` (MM 3/4/5) or ``MCPNX``/``MCPWNX`` (MM 27/28) command of ``pulse``."""
        if self.mode in MULTI_CHANNEL_MODES:
            n = self.source_number(pulse.channel)
            if pulse.sweeping:
                assert pulse.start is not None and pulse.stop is not None
                return flex.mcpwnx(n, pulse.channel, pulse.source, pulse.range, pulse.base, pulse.start, pulse.stop,
                                   pulse.comp)
            assert pulse.peak is not None
            return flex.mcpnx(n, pulse.channel, pulse.source, pulse.range, pulse.base, pulse.peak, pulse.comp)
        if pulse.sweeping:
            assert pulse.start is not None and pulse.stop is not None
            build = flex.pwv if pulse.source == "V" else flex.pwi
            return build(pulse.channel, self.wv_mode, pulse.range, pulse.base, pulse.start, pulse.stop, self.points,
                         pulse.comp)
        assert pulse.peak is not None
        build_bias = flex.pv if pulse.source == "V" else flex.pi
        return build_bias(pulse.channel, pulse.range, pulse.base, pulse.peak, pulse.comp)

    def _sync_command(self) -> list[str]:
        if self.sync is None:
            return []
        build = flex.wsv if self.sync.source == "V" else flex.wsi
        return [build(self.sync.channel, self.sync.range, self.sync.start, self.sync.stop, self.sync.comp)]

    def source_commands(self) -> list[str]:
        """The pulse source commands (MM 4: and the synchronous source, which a pulsed sweep command clears)."""
        out = [self.pulse_command(p) for p in self.pulses]
        return out + (self._sync_command() if self.mode == flex.PULSED_SWEEP_MODE else [])

    def commands(self) -> list[str]:
        """Every setup command in sending order (module docstring); ``XE`` is not part of the setup."""
        lines = [flex.ait(flex.PULSE_ADC, flex.PULSE_ADC_TIME_MODE, self.meas_time)]
        mm = [flex.mm(self.mode, self.measure), *(flex.cmm(ch, op) for ch, op in self.operation.items())]
        wm = [flex.wm(2 if self.auto_abort else 1, 1 if self.post == "start" else 2)] if self.mode in SWEEP_MODES \
            else []
        if self.mode in SINGLE_CHANNEL_MODES:
            lines += [*mm, flex.pt(self.hold, self.width, self.period)]
            if self.mode == flex.PULSED_BIAS_SWEEP_MODE:
                assert self.staircase is not None
                stair = self.staircase
                build = flex.wv if stair.source == "V" else flex.wi
                lines.append(build(stair.channel, self.wv_mode, stair.range, stair.start, stair.stop, self.points,
                                   stair.comp))
                lines += self._sync_command()
            lines += self.source_commands()
            return lines + wm
        lines.append(flex.mcpt(self.hold, self.period, 0.0, self.average, t0=self.t0))
        lines += [flex.mcpnt(p.channel, p.delay, p.width) for p in self.pulses]
        if self.mode == flex.MULTI_PULSED_SWEEP_MODE:
            lines.append(flex.mcpws(self.wv_mode, self.points))
        lines += self.source_commands()
        for item in self.wnx:
            lines.append(flex.wnx(self.source_number(item.channel), item.channel, item.source, item.range,
                                  item.start, item.stop, item.comp))
        return lines + mm + wm


class PulsedOps(DriverBase):
    """Pulsed operations of ``B1500Driver``: guarded ``MM 3/4/5/27/28`` setup and pulse-level updates."""

    def _check_pulsed(self, operation: str, setup: PulsedSetup, *, sources_only: bool = False) -> None:
        """Every pulse source (levels against the compliance, the train against the pulse envelope) and, unless
        ``sources_only``, every staircase/synchronous source at both ends, before anything is written."""
        for pulse in setup.pulses:
            guard = self._require_guard(operation, pulse.channel)
            for level in pulse.levels():
                guard.check(pulse.channel, pulse.source, level, pulse.comp)
            worst = pulse.extreme if pulse.source == "V" else abs(pulse.comp)
            base = pulse.base if pulse.source == "V" else abs(pulse.comp)
            guard.check_pulse(pulse.channel, base, worst, pulse.width, setup.period, setup.pulses_per_trigger, None)
        if sources_only:
            if setup.mode == flex.PULSED_SWEEP_MODE and setup.sync is not None:
                self._check_followers(operation, [setup.sync])
            return
        self._check_followers(operation, setup.followers)

    def _check_followers(self, operation: str, sources: list[SweepSource]) -> None:
        for source in sources:
            guard = self._require_guard(operation, source.channel)
            for level in source.levels():
                guard.check(source.channel, source.source, level, source.comp)

    def pulsed_setup(self, setup: PulsedSetup) -> None:
        """Guarded pulsed measurement setup (``PulsedSetup.commands``); every source passes the guard first (module
        docstring). ``XE`` is sent by ``execute_and_read``."""
        self._check_pulsed("pulsed_setup", setup)
        for cmd in setup.commands():
            self._write(cmd)

    def pulsed_update(self, setup: PulsedSetup) -> None:
        """Re-program the pulse sources of a set-up pulsed measurement between two triggers (a new pulse level of a
        host list): ``PulsedSetup.source_commands`` after the same guard checks. Mode, timing, measurement channels
        and staircase sources stay as set up."""
        self._check_pulsed("pulsed_update", setup, sources_only=True)
        for cmd in setup.source_commands():
            self._write(cmd)
