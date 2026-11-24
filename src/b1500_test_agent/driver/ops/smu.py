"""SMU operations: A/D converter, ranging, guarded DC force (voltage and current), spot measurement and staircase
sweep setup (blueprint 2.5).

``SmuOps`` is a mixin of ``B1500Driver``. Source operations (``force_v``, ``force_i``, ``staircase``) refuse without
an ``OutputGuard`` and check every channel and value against it before the first byte is written; command texts come
from ``driver/flex/smu.py`` and ``driver/flex/core.py`` (``MM``). ``spot_setup`` (``MM 1``, ``CMM``) sets no level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel, Integration, SweepTiming

ADC_TYPE_CODES: dict[str, int] = {"high_speed": 0, "high_resolution": 1}
"""``Integration.adc`` -> ``AAD``/``AIT`` type (PG PDF 351, 356)."""

ADC_MODE_CODES: dict[str, int] = {"auto": 0, "manual": 1, "plc": 2}
"""``Integration.mode`` -> ``AIT`` mode (PG PDF 357)."""

CmmMode = Annotated[int, Field(ge=0, le=4)]

MULTI_CHANNEL_SWEEP = 16
"""``MM 16``: multi-channel sweep, a ``WV``/``WI`` primary plus up to nine ``WNX`` sources (PG PDF 102, 471)."""

MAX_WNX_SOURCES = 9
"""``WNX`` sources besides the primary in MM 16 (``N`` = 2 to 10, PG PDF 557)."""


def _norm(channel: int) -> int:
    return channel * 100 + 1 if channel <= 10 else channel


def _same_polarity(start: float, stop: float) -> bool:
    return start != 0 and stop != 0 and (start > 0) == (stop > 0)


class SweepSource(StrictModel):
    """A sweep source that follows the primary sweep step by step (PG PDF 97, 102): the synchronous ``WSV``/``WSI``
    source of an MM 2 sweep (same output mode as the primary) or a ``WNX`` source of an MM 16 sweep (either mode).

    ``source`` is what the channel forces (``V`` or ``I``); it goes from ``start`` to ``stop`` in the primary's steps
    and sweep mode (linear/log, single/double); ``start`` = ``stop`` is a constant source. ``comp`` is the compliance
    (A for a voltage source, V for a current source; non-zero, polarity automatic), ``range`` the output ranging code
    (Table 4-4 for V, Table 4-5 for I; 0 = auto).
    """

    channel: Channel
    source: Literal["V", "I"]
    start: float
    stop: float
    comp: float
    range: int = 0

    @model_validator(mode="after")
    def _consistent(self) -> SweepSource:
        if self.comp == 0:
            raise ValueError("comp must be non-zero.")
        codes = flex.V_RANGE_CODES if self.source == "V" else flex.I_OUTPUT_RANGE_CODES
        if self.range not in codes:
            raise ValueError(f"range {self.range} is not an output ranging code of a {self.source} source.")
        return self

    def levels(self) -> tuple[float, float]:
        """``(start, stop)``."""
        return self.start, self.stop


class StaircaseSetup(StrictModel):
    """One staircase sweep: ``MM 2`` or ``MM 16``, ``CMM``, the primary ``WV``/``WI``, a synchronous ``WSV``/``WSI``
    (MM 2) or ``WNX`` sources (MM 16), ``WT``, ``WM`` (PG PDF 470-471, 380, 568-569, 551-552, 556-563, 564-565,
    552-553).

    The primary ``channel`` forces ``source`` (``V``: ``WV`` with current compliance ``icomp`` (A) on voltage output
    range code ``vrange``; ``I``: ``WI`` with voltage compliance ``vcomp`` (V) on current output range code
    ``irange``) from ``start`` to ``stop`` in ``points`` steps, ``sweep`` linear or log, ``double`` (start-stop-start,
    2 x points steps). ``sync`` is the one synchronous source of an MM 2 sweep (output mode = the primary's, PG PDF
    97); ``multi_channel`` selects MM 16, whose ``sources`` are the ``WNX`` sources ``N`` = 2, 3, ... in this order
    (either output mode; MM 16 without them is a legal one-source multi-channel sweep, PG Table 3-13). Every source
    follows the primary's steps and sweep mode; log sweeps need every source's start and stop non-zero and of one
    polarity. ``measure`` lists the measurement channels in measurement order (data order in each step).
    ``operation`` sets ``CMM`` for some of them (0 compliance side, 1 current, 2 voltage, 3 force side, 4
    synchronous I/V); unlisted channels keep their mode. ``auto_abort`` enables ``WM`` abort (stop on compliance,
    overflow or oscillation; data after the abort read ``199.999E+99``) and ``post`` chooses the output after a
    normal end.
    """

    channel: Channel
    start: float
    stop: float
    points: int = Field(ge=1, le=flex.MAX_SWEEP_STEPS)
    source: Literal["V", "I"] = "V"
    icomp: float | None = None
    vcomp: float | None = None
    vrange: int = 0
    irange: int = 0
    sweep: Literal["linear", "log"] = "linear"
    double: bool = False
    sync: SweepSource | None = None
    multi_channel: bool = False
    sources: tuple[SweepSource, ...] = Field(default=(), max_length=MAX_WNX_SOURCES)
    measure: tuple[Channel, ...] = Field(min_length=1, max_length=flex.MAX_CHANNELS_MM)
    operation: dict[Channel, CmmMode] = Field(default_factory=dict)
    timing: SweepTiming = Field(default_factory=SweepTiming)
    auto_abort: bool = True
    post: Literal["start", "stop"] = "start"

    @model_validator(mode="after")
    def _consistent(self) -> StaircaseSetup:
        if self.source == "V":
            if self.icomp is None or self.icomp == 0:
                raise ValueError("a voltage sweep (WV) needs a non-zero icomp.")
            if self.vcomp is not None or self.irange != 0:
                raise ValueError("vcomp and irange belong to a current sweep (WI).")
            if self.vrange not in flex.V_RANGE_CODES:
                raise ValueError(f"vrange {self.vrange} is not a PG Table 4-4 voltage output ranging code.")
        else:
            if self.vcomp is None or self.vcomp == 0:
                raise ValueError("a current sweep (WI) needs a non-zero vcomp.")
            if self.icomp is not None or self.vrange != 0:
                raise ValueError("icomp and vrange belong to a voltage sweep (WV).")
            if self.irange not in flex.I_OUTPUT_RANGE_CODES:
                raise ValueError(f"irange {self.irange} is not a PG Table 4-5 current output ranging code.")
        if len(set(self.measure)) != len(self.measure):
            raise ValueError("A measurement channel is listed twice.")
        if not set(self.operation) <= set(self.measure):
            raise ValueError("operation names a channel that is not measured.")
        if self.sync is not None and self.multi_channel:
            raise ValueError("a multi-channel sweep (MM 16) takes WNX sources, not a WSV/WSI synchronous source.")
        if self.sources and not self.multi_channel:
            raise ValueError("WNX sources need multi_channel (MM 16).")
        if self.sync is not None and self.sync.source != self.source:
            raise ValueError("the synchronous source must use the primary's output mode (WSV after WV, WSI after WI).")
        sources = [s.channel for s in self.followers]
        if len({_norm(ch) for ch in [self.channel, *sources]}) != len(sources) + 1:
            raise ValueError("a sweep source channel is listed twice.")
        if self.sweep == "log":
            for start, stop in [(self.start, self.stop), *(s.levels() for s in self.followers)]:
                if not _same_polarity(start, stop):
                    raise ValueError("A log sweep needs non-zero start and stop of the same polarity on every source.")
        return self

    @property
    def followers(self) -> list[SweepSource]:
        """The sources that follow the primary: the synchronous source or the ``WNX`` sources (in ``N`` order)."""
        return [self.sync] if self.sync is not None else list(self.sources)

    @property
    def mode(self) -> int:
        """``MM`` mode: 2 (staircase sweep) or 16 (multi-channel sweep)."""
        return MULTI_CHANNEL_SWEEP if self.multi_channel else 2

    @property
    def comp(self) -> float:
        """Compliance of the primary source (A for ``WV``, V for ``WI``)."""
        value = self.icomp if self.source == "V" else self.vcomp
        assert value is not None  # the validator guarantees it
        return value

    @property
    def wv_mode(self) -> int:
        """``WV``/``WI`` mode: 1 linear, 2 log, 3 linear double, 4 log double."""
        return (1 if self.sweep == "linear" else 2) + (2 if self.double else 0)

    def commands(self) -> list[str]:
        """The setup commands in sending order: ``MM``, ``CMM`` per ``operation``, ``WV``/``WI``, ``WSV``/``WSI`` or
        ``WNX`` (after the primary, which clears them), ``WT``, ``WM``. ``XE`` is not part of the setup."""
        timing = self.timing
        if self.source == "V":
            primary = flex.wv(self.channel, self.wv_mode, self.vrange, self.start, self.stop, self.points,
                              self.comp)
        else:
            primary = flex.wi(self.channel, self.wv_mode, self.irange, self.start, self.stop, self.points,
                              self.comp)
        followers: list[str] = []
        if self.sync is not None:
            build = flex.wsv if self.sync.source == "V" else flex.wsi
            followers.append(build(self.sync.channel, self.sync.range, self.sync.start, self.sync.stop,
                                   self.sync.comp))
        for n, item in enumerate(self.sources, start=2):
            followers.append(flex.wnx(n, item.channel, item.source, item.range, item.start, item.stop, item.comp))
        return [
            flex.mm(self.mode, self.measure),
            *(flex.cmm(ch, op) for ch, op in self.operation.items()),
            primary,
            *followers,
            flex.wt(timing.hold_s, timing.delay_s, timing.step_delay_s, timing.trigger_delay_s,
                    timing.measure_delay_s),
            flex.wm(2 if self.auto_abort else 1, 1 if self.post == "start" else 2),
        ]


class SmuOps(DriverBase):
    """SMU operations of ``B1500Driver``: integration, ranging, guarded ``DV``/``DI``, the spot setup (``MM 1``) and
    the staircase sweep setup (``WV``/``WI`` primary, ``WSV``/``WSI`` synchronous or ``WNX`` multi-channel sources);
    the conditioning settings ``FL``/``SSR`` (channel allowlist checked), ``AZ``, ``AV``, ``RM`` and ``WNCC``. No v2
    kind sends a conditioning command (each keeps its initial setting); a kind that does restores it in cleanup."""

    def set_integration(self, adc: int, mode: int, n: float, *, chs: Sequence[int] = ()) -> None:
        """``AAD ch,adc`` for each of ``chs``, then ``AIT adc,mode,n`` (PG PDF 351, 356-359)."""
        cmds = [flex.aad(ch, adc) for ch in chs] + [flex.ait(adc, mode, n)]
        for cmd in cmds:
            self._write(cmd)

    def apply_integration(self, integration: Integration, chs: Sequence[int]) -> None:
        """``set_integration`` from an ``Integration`` model (ADC type, mode and N)."""
        self.set_integration(ADC_TYPE_CODES[integration.adc], ADC_MODE_CODES[integration.mode], integration.n, chs=chs)

    def set_range(self, ch: int, quantity: Literal["I", "V"], code: int) -> None:
        """``RI``/``RV`` measurement ranging (PG PDF 501, 503); codes via ``driver.modules.ranging_code``."""
        if quantity == "I":
            self._write(flex.ri(ch, code))
        elif quantity == "V":
            self._write(flex.rv(ch, code))
        else:
            raise ValueError(f"quantity must be 'I' or 'V', got {quantity!r}")

    # -- conditioning (WP7.7, blueprint v2 1.2: RM, AV, AZ, FL, SSR) ------------------------------------------------

    def set_filter(self, on: bool, chs: Sequence[int]) -> None:
        """``FL mode,ch...`` on named channels only (each in the guard's allowlist; PG PDF 436): the filter changes
        the output path, so it is never sent to every channel."""
        if not chs:
            raise ValueError("set_filter needs the channels (FL without channels would reach every SMU)")
        for ch in chs:
            self._require_guard("set_filter", ch).check_channel(ch)
        self._write(flex.fl(on, list(chs)))

    def set_series_resistor(self, ch: int, on: bool) -> None:
        """``SSR ch,mode`` for a channel in the guard's allowlist (PG PDF 521); with the output switch closed the
        output forces 0 V for a moment."""
        self._require_guard("set_series_resistor", ch).check_channel(ch)
        self._write(flex.ssr(ch, on))

    def set_adc_zero(self, on: bool) -> None:
        """``AZ mode``: ADC zero function of the high-resolution ADC (PG PDF 363); no output change."""
        self._write(flex.az(on))

    def set_averaging(self, number: int, mode: int | None = None) -> None:
        """``AV number[,mode]``: high-speed ADC averaging (PG PDF 362-363); no output change."""
        self._write(flex.av(number, mode))

    def set_range_mode(self, ch: int, mode: int, rate: int | None = None) -> None:
        """``RM ch,mode[,rate]``: auto-ranging operation of a current measurement (PG PDF 501-502); no output
        change."""
        self._write(flex.rm(ch, mode, rate))

    def clear_sweep_sources(self) -> None:
        """``WNCC``: clears the multi-channel sweep sources set by ``WNX`` (PG PDF 556); no output change."""
        self._write(flex.wncc())

    def force_v(self, ch: int, v: float, *, icomp: float, rng: int = 0) -> None:
        """Guarded ``DV ch,rng,v,icomp`` (PG PDF 396)."""
        self._require_guard("force_v", ch).check(ch, "V", v, icomp)
        self._write(flex.dv(ch, rng, v, icomp))

    def force_i(self, ch: int, i: float, *, vcomp: float, rng: int = 0) -> None:
        """Guarded ``DI ch,rng,i,vcomp`` (PG PDF 391-392): the current against the channel's current envelope, the
        voltage compliance against its voltage envelope."""
        self._require_guard("force_i", ch).check(ch, "I", i, vcomp)
        self._write(flex.di(ch, rng, i, vcomp))

    def spot_setup(self, measure: Sequence[int], operation: Mapping[int, int]) -> None:
        """Spot measurement setup: ``MM 1,<measure>`` and ``CMM`` per ``operation`` (PG PDF 470-471, 380). Not a
        source command (the channels' levels were set by ``force_v``/``force_i``); ``XE`` is sent by
        ``execute_and_read``. ``operation`` may only name measured channels."""
        if not set(operation) <= set(measure):
            raise ValueError("operation names a channel that is not measured")
        self._write(flex.mm(1, measure))
        for ch, op in operation.items():
            self._write(flex.cmm(ch, op))

    def staircase(self, setup: StaircaseSetup) -> None:
        """Guarded staircase sweep setup (``StaircaseSetup.commands``: ``MM 2|16``, ``CMM``, ``WV``/``WI``,
        ``WSV``/``WSI`` or ``WNX``, ``WT``, ``WM``). Both end points of every source are checked against the guard
        before anything is written; ``XE`` is sent by ``execute_and_read``."""
        guard = self._require_guard("staircase", setup.channel)
        guard.check(setup.channel, setup.source, setup.start, setup.comp)
        guard.check(setup.channel, setup.source, setup.stop, setup.comp)
        for follower in setup.followers:
            for level in follower.levels():
                guard.check(follower.channel, follower.source, level, follower.comp)
        for cmd in setup.commands():
            self._write(cmd)

    def staircase_v(self, setup: StaircaseSetup) -> None:
        """The v1 entry point: a staircase sweep with a voltage (``WV``) primary; see ``staircase``."""
        if setup.source != "V":
            raise ValueError("staircase_v sets a voltage primary sweep; use staircase for a WI primary.")
        self.staircase(setup)
