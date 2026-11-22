"""MFCMU operations (blueprint v2 2.5): signal, measurement setups of MM 17-26, phase compensation, data correction
and the cleanup zeroing (WP8.1).

``CmuOps`` is a mixin of ``B1500Driver``, grouped as A (queries: correction state, frequency list and standards,
phase compensation mode and result), B (settings without an output change: ``IMP``, ``RC``, ``ACT``, ``LMN``,
``ADJ``, the correction list, standards and switches), C (guarded sources: every ``FC``/``ACV``/``DCV`` and sweep,
pulse or sampling source goes through ``OutputGuard.check_ac`` with the channel's resulting frequency, AC level and
DC bias before anything is written; the correction and phase compensation measurements apply the signal too) and D
(measurement: ``MM`` + ``XE`` + parse into ``CmuReading``s). Command texts come from ``driver/flex/cmu.py`` (and
``core.mm``).

The driver remembers, per transaction, what it programmed on each MFCMU (``CmuTracking``): the signal (starting
from the ``CN`` condition 1 kHz, 0 V rms, 0 V, PG PDF 382/442), the channels it set to a non-zero AC level or DC
bias, the ``IMP`` mode and ``LMN`` setting (for the data layout) and the correction frequency list it wrote (a
``CORR?`` applies the AC level at every listed frequency, so it is refused unless this driver wrote the list, or read
it back with ``correction_frequencies``, and the guard admits every frequency). ``zero_cmu`` (cleanup step 4,
blueprint v2 2.6) sends ``DCV ch,0`` and ``ACV ch,0`` to those channels whose ``LOP?`` code still shows the output
switch on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, model_validator

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import (
    CmuLayout,
    CmuReading,
    parse_adj_mode,
    parse_cmu_blocks,
    parse_corr_result,
    parse_corrl_count,
    parse_corrl_frequency,
    parse_dcorr,
)
from b1500_test_agent.driver.discovery import parse_adj, parse_corrst, parse_lop
from b1500_test_agent.driver.errors import DriverStateError
from b1500_test_agent.driver.ops.core import DriverBase, RawBlock
from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.station import CmuCorrectionLive, CorrectionFunction

CN_FREQ_HZ = 1.0e3
"""MFCMU signal frequency after ``CN``/``CL``/``IN`` (PG PDF 382, 442: 1 kHz, AC 0 V, DC 0 V, range 50 Ohm)."""

PHASE_COMPENSATION_TIMEOUT_S = 90.0
"""Read timeout of ``ADJ? chnum,1``: the manual quotes about 30 s (PG PDF 355); three times that."""

Post = Literal["start", "stop"]


class CmuSignal(StrictModel):
    """The MFCMU output signal: frequency (Hz), oscillator level (V rms) and DC bias (V)."""

    freq_hz: float = Field(default=CN_FREQ_HZ, ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    ac_vrms: float = Field(default=0.0, ge=0.0, le=flex.CMU_MAX_AC_V)
    dc_v: float = Field(default=0.0, ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)


class CmuSweepTiming(StrictModel):
    """``WTDCV``/``WTFC``/``WTACV`` timing in seconds: hold, delay, step delay, step source and step measurement
    trigger delays (PG PDF 565-568)."""

    hold_s: float = Field(default=0.0, ge=0.0, le=655.35)
    delay_s: float = Field(default=0.0, ge=0.0, le=655.35)
    step_delay_s: float = Field(default=0.0, ge=0.0, le=1.0)
    trigger_delay_s: float = Field(default=0.0, ge=0.0, le=65.535)
    measure_delay_s: float = Field(default=0.0, ge=0.0, le=65.535)

    def values(self) -> tuple[float, float, float, float, float]:
        return (self.hold_s, self.delay_s, self.step_delay_s, self.trigger_delay_s, self.measure_delay_s)


class _Sweep(StrictModel):
    channel: Channel
    points: int = Field(ge=1, le=flex.CMU_MAX_STEPS)
    sweep: Literal["linear", "log"] = "linear"
    double: bool = False
    timing: CmuSweepTiming = Field(default_factory=CmuSweepTiming)
    auto_abort: bool = True
    post: Post = "start"

    @property
    def sweep_mode(self) -> int:
        """``WDCV``/``WFC``/``WACV`` mode: 1 linear, 2 log, 3 linear double, 4 log double."""
        return (1 if self.sweep == "linear" else 2) + (2 if self.double else 0)

    @property
    def steps(self) -> int:
        """Data blocks the sweep returns (a double sweep returns ``2 x points``)."""
        return self.points * (2 if self.double else 1)


class CvSweepSetup(_Sweep):
    """C-V (DC bias) sweep, MM 18 (PG PDF 549-550, 554-555, 566-567): DC bias from ``start`` to ``stop`` (V) at
    ``freq_hz`` and ``ac_vrms``; ``measure_smu`` adds SMU measurement channels (measured before the MFCMU at each
    step, data in that order after it)."""

    start: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    stop: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    freq_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    ac_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    measure_smu: tuple[Channel, ...] = Field(default=(), max_length=9)

    @model_validator(mode="after")
    def _consistent(self) -> CvSweepSetup:
        if self.sweep == "log" and (self.start == 0 or self.stop == 0 or (self.start > 0) != (self.stop > 0)):
            raise ValueError("A log DC bias sweep needs non-zero start and stop of the same polarity.")
        if self.timing.delay_s > 65.535:
            raise ValueError("WTDCV delay is at most 65.535 s.")
        return self

    @property
    def mode(self) -> int:
        return 18


class CfSweepSetup(_Sweep):
    """C-f sweep, MM 22 (PG PDF 550-551, 555-556, 567-568): frequency from ``start_hz`` to ``stop_hz`` at
    ``ac_vrms`` and ``dc_v``."""

    start_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    stop_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    ac_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    dc_v: float = Field(default=0.0, ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)

    @property
    def mode(self) -> int:
        return 22


class AcLevelSweepSetup(_Sweep):
    """C-V (AC level) sweep, MM 23 (PG PDF 547, 553-554, 565-566): oscillator level from ``start_vrms`` to
    ``stop_vrms`` at ``freq_hz`` and ``dc_v``."""

    start_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    stop_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    freq_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    dc_v: float = Field(default=0.0, ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)

    @model_validator(mode="after")
    def _log(self) -> AcLevelSweepSetup:
        if self.sweep == "log" and (self.start_vrms == 0 or self.stop_vrms == 0):
            raise ValueError("A log AC level sweep needs non-zero start and stop.")
        return self

    @property
    def mode(self) -> int:
        return 23


class _Pulse(StrictModel):
    channel: Channel
    base: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    freq_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    ac_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    hold_s: float = Field(default=0.0, ge=0.0, le=655.35)
    width_s: float = Field(default=flex.PTDCV_MIN_WIDTH_S, ge=flex.PTDCV_MIN_WIDTH_S, le=655.35)
    period_s: float = Field(default=0.0, ge=0.0, le=655.35)


class PulsedSpotCSetup(_Pulse):
    """Pulsed spot C, MM 19 (PG PDF 484-485, 487-488): ``base`` then ``pulse`` (V); measured during the pulse."""

    pulse: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)

    @property
    def mode(self) -> int:
        return 19


class PulsedCvSweepSetup(_Pulse):
    """Pulsed sweep C-V, MM 20 (PG PDF 487-490, 554-555): pulse peaks from ``start`` to ``stop`` (linear) over
    ``base``; ``WMDCV`` sets the abort and the post value (the pulse base)."""

    start: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    stop: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    points: int = Field(ge=1, le=flex.CMU_MAX_STEPS)
    double: bool = False
    auto_abort: bool = True

    @property
    def mode(self) -> int:
        return 20

    @property
    def steps(self) -> int:
        return self.points * (2 if self.double else 1)


class CtSamplingSetup(StrictModel):
    """C-t sampling, MM 26 (PG PDF 467-468, 476-477): ``base`` for ``hold_base_s``, then ``bias``; ``number``
    samples every ``interval_s`` from ``hold_bias_s`` after the bias step; ``post`` = DC bias after a normal end
    (``None``: the instrument keeps its previous post value)."""

    channel: Channel
    base: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    bias: float = Field(ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    post: float | None = Field(default=None, ge=-flex.CMU_MAX_DC_V, le=flex.CMU_MAX_DC_V)
    freq_hz: float = Field(ge=flex.CMU_FREQ_HZ[0], le=flex.CMU_FREQ_HZ[1])
    ac_vrms: float = Field(ge=0.0, le=flex.CMU_MAX_AC_V)
    hold_bias_s: float = Field(default=0.0, ge=0.0, le=655.35)
    interval_s: float = Field(default=0.01, ge=0.008, le=655.35)
    number: int = Field(default=1000, ge=1, le=10001)
    hold_base_s: float = Field(default=0.0, ge=0.0, le=655.35)

    @property
    def mode(self) -> int:
        return 26


@dataclass
class CmuTracking:
    """What this driver programmed on the MFCMUs (see the module docstring)."""

    signals: dict[int, CmuSignal] = field(default_factory=dict)
    active: set[int] = field(default_factory=set)
    corr_freqs: dict[int, tuple[float, ...]] = field(default_factory=dict)
    imp: int = flex.IMP_INITIAL
    monitor: bool = False


@dataclass(frozen=True)
class CmuBlock:
    """One MFCMU measurement read: the raw block (exact text, elements, timing) and its readings."""

    raw: RawBlock
    layout: CmuLayout
    readings: tuple[CmuReading, ...]


def _canonical(ch: int) -> int:
    return ch // 100 if ch > 10 and ch % 100 == 1 else ch


class CmuOps(DriverBase):
    """MFCMU operations of ``B1500Driver`` (see the module docstring)."""

    @property
    def cmu_tracking(self) -> CmuTracking:
        """The per-driver record of the MFCMU programming (created on first use)."""
        tracking = self.__dict__.get("_cmu_tracking")
        if tracking is None:
            tracking = CmuTracking()
            self.__dict__["_cmu_tracking"] = tracking
        return tracking

    def _signal(self, ch: int) -> CmuSignal:
        return self.cmu_tracking.signals.get(_canonical(ch), CmuSignal())

    def _track(self, ch: int, signal: CmuSignal) -> None:
        tracking = self.cmu_tracking
        tracking.signals[_canonical(ch)] = signal
        if signal.ac_vrms != 0 or signal.dc_v != 0:
            tracking.active.add(_canonical(ch))

    def _check(self, operation: str, ch: int, *signals: CmuSignal) -> None:
        guard = self._require_guard(operation, ch)
        for signal in signals:
            guard.check_ac(ch, signal.ac_vrms, signal.dc_v, signal.freq_hz)

    def _write_all(self, cmds: Sequence[str]) -> None:
        for cmd in cmds:
            self._write(cmd)

    # -- A: queries ---------------------------------------------------------------------------------------------

    def correction_enabled(self, ch: int, corr: CorrectionFunction) -> bool:
        """``CORRST? ch,corr`` -> whether the open, short or load correction function is ON (PG PDF 388)."""
        return parse_corrst(self._query(flex.corrst_q(ch, corr)))

    def phase_compensation_result(self, ch: int) -> int:
        """``ADJ? ch,0`` -> the result of the last phase compensation without measuring (PG PDF 355-356): 0
        completed, 1 failed, 2 aborted, 3 not performed (``flex.ADJ_RESULTS``). Never sends mode 1, which measures
        for about 30 s and resets the MFCMU."""
        return parse_adj(self._query(flex.adj_q(ch, flex.ADJ_READ_LAST)))

    def phase_compensation_mode(self, ch: int) -> int:
        """``*LRN? 90`` -> the phase compensation mode of MFCMU ``ch``: 0 auto, 1 manual, 2 load adaptive (PG
        PDF 452, 355). A query."""
        return parse_adj_mode(self._query(flex.lrn_q(flex.LRN_ADJ_MODE)), ch)

    def correction_state(self, ch: int) -> CmuCorrectionLive:
        """``CORRST?`` for open, short and load, ``ADJ? ch,0`` and ``*LRN? 90``: the live correction state of one
        MFCMU. ``phase`` is True when phase compensation data are in effect: the load adaptive mode (compensated
        before every measurement), or the manual mode with a completed compensation; in the auto mode (initial
        setting, restored by ``*RST``) the measured compensation data are not used."""
        corr_state = {corr: self.correction_enabled(ch, corr) for corr in flex.CORRECTION_CODES}
        result = self.phase_compensation_result(ch)
        mode = self.phase_compensation_mode(ch)
        phase = mode == 2 or (mode == flex.ADJ_MANUAL and result == 0)
        return CmuCorrectionLive(corr_state=corr_state, phase=phase)

    def correction_frequencies(self, ch: int) -> tuple[float, ...]:
        """``CORRL? ch`` and ``CORRL? ch,index`` for every entry: the correction frequency list stored in the MFCMU,
        sorted (PG PDF 385). Queries only. The list read back is remembered like one written by
        ``set_correction_frequencies``, so ``measure_correction`` can check every listed frequency against the guard
        without rewriting the list (which would clear the data of the other corrections, WP8.2)."""
        count = parse_corrl_count(self._query(flex.corrl_q(ch)))
        freqs = tuple(sorted({parse_corrl_frequency(self._query(flex.corrl_q(ch, i))) for i in range(1, count + 1)}))
        self.cmu_tracking.corr_freqs[_canonical(ch)] = freqs
        return freqs

    def correction_standard(self, ch: int, corr: CorrectionFunction) -> tuple[int, float, float]:
        """``DCORR? ch,corr`` -> ``(mode, primary, secondary)``: the reference value of the open (100: Cp, G), short or
        load (400: Ls, Rs) standard (PG PDF 389-390). A query."""
        return parse_dcorr(self._query(flex.dcorr_q(ch, corr)))

    # -- B: settings without an output change -------------------------------------------------------------------

    def set_impedance_model(self, mode: int) -> None:
        """``IMP mode``: the parameter pair of the MFCMU data (Table 4-16, PDF 347; PG PDF 441)."""
        self._write(flex.imp(mode))
        self.cmu_tracking.imp = mode

    def set_cmu_range(self, ch: int, range_ohm: int | None = None) -> None:
        """``RC ch,0`` (auto, ``range_ohm`` None) or ``RC ch,2,range`` (fixed; Table 4-17, PDF 348; PG PDF 500)."""
        self._write(flex.rc(ch, 0) if range_ohm is None else flex.rc(ch, 2, range_ohm))

    def set_cmu_integration(self, mode: int, n: int) -> None:
        """``ACT mode,N``: MFCMU averaging, 0 auto (N x initial) or 2 power-line cycles (PG PDF 354)."""
        self._write(flex.act(mode, n))

    def set_cmu_monitor(self, on: bool) -> None:
        """``LMN 1|0``: add the oscillator level and DC bias monitors to the MM 17/18/22/23 data (PG PDF 445)."""
        self._write(flex.lmn(1 if on else 0))
        self.cmu_tracking.monitor = on

    def set_phase_compensation_mode(self, ch: int, mode: int) -> None:
        """``ADJ ch,mode``: 0 auto, 1 manual, 2 load adaptive (PG PDF 355). The command initializes the MFCMU, so the
        tracked signal returns to the ``CN`` condition."""
        self._write(flex.adj(ch, mode))
        self._initialized(ch)

    def _initialized(self, ch: int) -> None:
        tracking = self.cmu_tracking
        tracking.signals.pop(_canonical(ch), None)
        tracking.active.discard(_canonical(ch))

    def set_correction_frequencies(self, ch: int, freqs: Sequence[float] = (), *, defaults: bool = False) -> None:
        """``CLCORR ch,1`` (or ``ch,2`` with ``defaults``: the 23 default frequencies, PG PDF 379), then ``CORRL ch,f``
        for each of ``freqs`` (PG PDF 384). Both turn the correction functions off and clear the correction data. The
        list is remembered for ``measure_correction``'s guard check."""
        cmds = [flex.clcorr(ch, 2 if defaults else 1), *(flex.corrl(ch, f) for f in freqs)]
        self._write_all(cmds)
        base = flex.CLCORR_DEFAULT_FREQS_HZ if defaults else ()
        self.cmu_tracking.corr_freqs[_canonical(ch)] = tuple(sorted({*base, *(float(f) for f in freqs)}))

    def set_correction_standard(self, ch: int, corr: CorrectionFunction, primary: float, secondary: float) -> None:
        """``DCORR ch,corr,mode,primary,secondary``: the open (Cp F, G S) or short/load (Ls H, Rs Ohm) standard's
        reference value (PG PDF 389). Turns the correction functions off and clears the correction data."""
        self._write(flex.dcorr(ch, corr, flex.DCORR_MODES[corr], primary, secondary))

    def set_correction(self, ch: int, corr: CorrectionFunction, on: bool) -> None:
        """``CORRST ch,corr,1|0``: switch one correction function (PG PDF 387-388)."""
        self._write(flex.corrst(ch, corr, on))

    def set_correction_data(self, ch: int, freq_hz: float, *, open_g: float, open_b: float, short_r: float,
                            short_x: float, load_r: float, load_x: float) -> None:
        """``CORRDT``: the correction data of one frequency (open as G, B in S; short and load as R, X in Ohm; PG
        PDF 383-384)."""
        self._write(flex.corrdt(ch, freq_hz, open_g, open_b, short_r, short_x, load_r, load_x))

    # -- C: guarded sources -------------------------------------------------------------------------------------

    def apply_cmu_signal(self, ch: int, signal: CmuSignal) -> None:
        """Guarded ``FC``, ``ACV``, ``DCV`` (PG PDF 435, 354, 390): the resulting frequency, AC level and DC bias are
        checked once with ``OutputGuard.check_ac``; every intermediate state lies inside the same envelope."""
        self._check("apply_cmu_signal", ch, signal)
        self._write_all([flex.fc(ch, signal.freq_hz), flex.acv(ch, signal.ac_vrms), flex.dcv(ch, signal.dc_v)])
        self._track(ch, signal)

    def set_cmu_frequency(self, ch: int, freq_hz: float) -> None:
        """Guarded ``FC ch,freq`` with the channel's present AC level and DC bias (PG PDF 435)."""
        signal = self._signal(ch).model_copy(update={"freq_hz": float(freq_hz)})
        self._check("set_cmu_frequency", ch, signal)
        self._write(flex.fc(ch, freq_hz))
        self._track(ch, signal)

    def set_cmu_ac(self, ch: int, vrms: float) -> None:
        """Guarded ``ACV ch,level`` at the channel's present frequency and DC bias (PG PDF 354-355)."""
        signal = self._signal(ch).model_copy(update={"ac_vrms": float(vrms)})
        self._check("set_cmu_ac", ch, signal)
        self._write(flex.acv(ch, vrms))
        self._track(ch, signal)

    def set_cmu_dc(self, ch: int, v: float) -> None:
        """Guarded ``DCV ch,voltage`` at the channel's present frequency and AC level (PG PDF 390-391)."""
        signal = self._signal(ch).model_copy(update={"dc_v": float(v)})
        self._check("set_cmu_dc", ch, signal)
        self._write(flex.dcv(ch, v))
        self._track(ch, signal)

    def spot_c(self, ch: int) -> None:
        """``MM 17,ch``: spot C with the signal set by ``apply_cmu_signal`` (PG PDF 470-471); ``XE`` by
        ``measure_cmu``. No output change."""
        self._write(flex.mm(17, [ch]))

    def cv_sweep(self, setup: CvSweepSetup) -> None:
        """Guarded C-V (DC bias) sweep setup: ``MM 18,ch[,smu...]``, ``FC``, ``ACV``, ``WTDCV``, ``WMDCV``, ``WDCV``
        (PG PDF 470, 435, 354, 566, 554, 549). Both DC end points are checked at the sweep's frequency and level."""
        ends = [CmuSignal(freq_hz=setup.freq_hz, ac_vrms=setup.ac_vrms, dc_v=v) for v in (setup.start, setup.stop)]
        self._check("cv_sweep", setup.channel, *ends)
        ch = setup.channel
        self._write_all([
            flex.mm(18, [ch, *setup.measure_smu]), flex.fc(ch, setup.freq_hz), flex.acv(ch, setup.ac_vrms),
            flex.wtdcv(*setup.timing.values()), flex.wmdcv(2 if setup.auto_abort else 1, _post(setup.post)),
            flex.wdcv(ch, setup.sweep_mode, setup.start, setup.stop, setup.points),
        ])
        self._track_sweep(ch, ends, setup.post)

    def cf_sweep(self, setup: CfSweepSetup) -> None:
        """Guarded C-f sweep setup: ``MM 22,ch``, ``ACV``, ``DCV``, ``WTFC``, ``WMFC``, ``WFC`` (PG PDF 470, 354, 390,
        567, 555, 550). Both frequency end points are checked at the sweep's level and bias."""
        ends = [CmuSignal(freq_hz=f, ac_vrms=setup.ac_vrms, dc_v=setup.dc_v) for f in (setup.start_hz, setup.stop_hz)]
        self._check("cf_sweep", setup.channel, *ends)
        ch = setup.channel
        self._write_all([
            flex.mm(22, [ch]), flex.fc(ch, setup.start_hz), flex.acv(ch, setup.ac_vrms), flex.dcv(ch, setup.dc_v),
            flex.wtfc(*setup.timing.values()), flex.wmfc(2 if setup.auto_abort else 1, _post(setup.post)),
            flex.wfc(ch, setup.sweep_mode, setup.start_hz, setup.stop_hz, setup.points),
        ])
        self._track_sweep(ch, ends, setup.post)

    def ac_level_sweep(self, setup: AcLevelSweepSetup) -> None:
        """Guarded C-V (AC level) sweep setup: ``MM 23,ch``, ``FC``, ``DCV``, ``WTACV``, ``WMACV``, ``WACV`` (PG
        PDF 470, 435, 390, 565, 553, 547). Both AC end points are checked at the sweep's frequency and bias."""
        ends = [CmuSignal(freq_hz=setup.freq_hz, ac_vrms=v, dc_v=setup.dc_v)
                for v in (setup.start_vrms, setup.stop_vrms)]
        self._check("ac_level_sweep", setup.channel, *ends)
        ch = setup.channel
        self._write_all([
            flex.mm(23, [ch]), flex.fc(ch, setup.freq_hz), flex.dcv(ch, setup.dc_v),
            flex.wtacv(*setup.timing.values()), flex.wmacv(2 if setup.auto_abort else 1, _post(setup.post)),
            flex.wacv(ch, setup.sweep_mode, setup.start_vrms, setup.stop_vrms, setup.points),
        ])
        self._track_sweep(ch, ends, setup.post)

    def pulsed_spot_c(self, setup: PulsedSpotCSetup) -> None:
        """Guarded pulsed spot C setup: ``MM 19,ch``, ``FC``, ``ACV``, ``PTDCV``, ``PDCV`` (PG PDF 470, 435, 354,
        487, 484). Base and pulse are checked; the MFCMU returns to the base after the pulse."""
        levels = [CmuSignal(freq_hz=setup.freq_hz, ac_vrms=setup.ac_vrms, dc_v=v) for v in (setup.base, setup.pulse)]
        self._check("pulsed_spot_c", setup.channel, *levels)
        ch = setup.channel
        self._write_all([
            flex.mm(19, [ch]), flex.fc(ch, setup.freq_hz), flex.acv(ch, setup.ac_vrms),
            flex.ptdcv(setup.hold_s, setup.width_s, setup.period_s), flex.pdcv(ch, setup.base, setup.pulse),
        ])
        self._track(ch, levels[0])
        self.cmu_tracking.active.add(_canonical(ch))

    def pulsed_cv_sweep(self, setup: PulsedCvSweepSetup) -> None:
        """Guarded pulsed sweep C-V setup: ``MM 20,ch``, ``FC``, ``ACV``, ``WMDCV``, ``PTDCV``, ``PWDCV`` (PG PDF 470,
        435, 354, 554, 487, 489). Base, start and stop are checked."""
        levels = [CmuSignal(freq_hz=setup.freq_hz, ac_vrms=setup.ac_vrms, dc_v=v)
                  for v in (setup.base, setup.start, setup.stop)]
        self._check("pulsed_cv_sweep", setup.channel, *levels)
        ch = setup.channel
        self._write_all([
            flex.mm(20, [ch]), flex.fc(ch, setup.freq_hz), flex.acv(ch, setup.ac_vrms),
            flex.wmdcv(2 if setup.auto_abort else 1, 1), flex.ptdcv(setup.hold_s, setup.width_s, setup.period_s),
            flex.pwdcv(ch, 3 if setup.double else 1, setup.base, setup.start, setup.stop, setup.points),
        ])
        self._track(ch, levels[0])
        self.cmu_tracking.active.add(_canonical(ch))

    def ct_sampling(self, setup: CtSamplingSetup) -> None:
        """Guarded C-t sampling setup: ``MM 26,ch``, ``FC``, ``ACV``, ``MTDCV``, ``MDCV`` (PG PDF 470, 435, 354, 476,
        467). Base, bias and post are checked."""
        dcs = [setup.base, setup.bias] + ([] if setup.post is None else [setup.post])
        levels = [CmuSignal(freq_hz=setup.freq_hz, ac_vrms=setup.ac_vrms, dc_v=v) for v in dcs]
        self._check("ct_sampling", setup.channel, *levels)
        ch = setup.channel
        self._write_all([
            flex.mm(26, [ch]), flex.fc(ch, setup.freq_hz), flex.acv(ch, setup.ac_vrms),
            flex.mtdcv(setup.hold_bias_s, setup.interval_s, setup.number, setup.hold_base_s),
            flex.mdcv(ch, setup.base, setup.bias, setup.post),
        ])
        self._track(ch, levels[0])
        self.cmu_tracking.active.add(_canonical(ch))

    def _track_sweep(self, ch: int, ends: list[CmuSignal], post: Post) -> None:
        self._track(ch, ends[0] if post == "start" else ends[1])
        if any(e.ac_vrms or e.dc_v for e in ends):
            self.cmu_tracking.active.add(_canonical(ch))

    def measure_phase_compensation(self, ch: int, *, timeout_s: float = PHASE_COMPENSATION_TIMEOUT_S) -> int:
        """``ADJ? ch,1``: measure the phase compensation data (about 30 s; the human has opened the terminals at the
        device end; needs ``set_phase_compensation_mode(ch, 1)`` first; resets the MFCMU; PG PDF 355-356) and return
        the result (``flex.ADJ_RESULTS``). The channel must be in the guard's allowlist (the MFCMU drives its own
        signal during it)."""
        self._require_guard("measure_phase_compensation", ch).check_channel(ch)
        result = parse_adj(self._query(flex.adj_q(ch, flex.ADJ_MEASURE), timeout_s=timeout_s))
        self._initialized(ch)
        return result

    def measure_correction(self, ch: int, corr: CorrectionFunction, *, timeout_s: float | None = None) -> int:
        """``CORR? ch,corr``: measure the open, short or load correction data at every listed frequency with the
        present AC level (PG PDF 382-383) and return 0 completed, 1 failed, 2 aborted. The human has connected the
        standard (or opened/shorted the terminals at the device end) first. Refused unless this driver wrote the
        frequency list (``set_correction_frequencies``) or read it back (``correction_frequencies``) and the guard
        admits the AC level and DC bias at every listed frequency.

        Raises:
            DriverStateError: If this driver neither wrote nor read the frequency list.
            EnvelopeViolation: If a listed frequency is outside the channel's AC envelope.
        """
        freqs = self.cmu_tracking.corr_freqs.get(_canonical(ch))
        if not freqs:
            raise DriverStateError(f"correction data measurement on channel {ch} refused: write the correction "
                                   "frequency list in this transaction first (set_correction_frequencies) or read it "
                                   "back (correction_frequencies), so every frequency can be checked")
        present = self._signal(ch)
        self._check("measure_correction", ch, *(present.model_copy(update={"freq_hz": f}) for f in freqs))
        return parse_corr_result(self._query(flex.corr_q(ch, corr), timeout_s=timeout_s))

    # -- D: measurement -----------------------------------------------------------------------------------------

    def cmu_layout(self, mode: int, *, smu_channels: int = 0, timestamp: bool = False) -> CmuLayout:
        """The data layout of an MFCMU measurement in ``mode`` from this driver's ``IMP``/``LMN``/``FMT`` settings
        (``timestamp``: ``TSC 1`` is on)."""
        _fmt, fmt_mode = self.data_format
        tracking = self.cmu_tracking
        return CmuLayout(imp=tracking.imp, mode=mode, monitor=tracking.monitor, source=fmt_mode == 1,
                         timestamp=timestamp, index=fmt_mode != 0, smu_channels=smu_channels)

    def measure_cmu(self, layout: CmuLayout, *, steps: int, timeout_s: float) -> CmuBlock:
        """``XE`` and the read of an MFCMU measurement set up before (``steps`` data blocks), parsed into
        ``CmuReading``s (``driver.cmu_data``; PG PDF 47-49). An aborted sweep returns fewer readings (the raw block
        then reports ``complete`` False).

        Raises:
            FlexParseError: If the response does not fit ``layout``; ``raw`` holds the text.
        """
        raw = self.execute_and_read(expected_points=steps * layout.width, timeout_s=timeout_s)
        usable = len(raw.points) - len(raw.points) % layout.width
        readings = parse_cmu_blocks(raw.points[:usable], layout)
        return CmuBlock(raw=raw, layout=layout, readings=tuple(readings))

    # -- cleanup ------------------------------------------------------------------------------------------------

    @property
    def cmu_channels_in_use(self) -> list[int]:
        """MFCMU channels this driver set to a non-zero AC level or DC bias (sorted)."""
        return sorted(self.cmu_tracking.active)

    def zero_cmu(self) -> list[int]:
        """Cleanup step 4 (blueprint v2 2.6): ``DCV ch,0`` and ``ACV ch,0`` for every channel of
        ``cmu_channels_in_use`` whose ``LOP?`` code shows the output switch on (``DCV``/``ACV`` need it; a switch
        already off left the MFCMU at 0 V and 0 V rms, PG PDF 382/442). Never gated (it only lowers levels); aborts a
        pending measurement first. Returns the channels zeroed.
        """
        channels = self.cmu_channels_in_use
        if not channels:
            return []
        if self._measurement_pending:
            self.abort()
        states = parse_lop(self._query(flex.LOP_Q))
        zeroed = [ch for ch in channels if states.get(ch) is not None and states[ch].output_on]
        for ch in zeroed:
            self._write(flex.dcv(ch, 0.0))
            self._write(flex.acv(ch, 0.0))
        self.cmu_tracking.active.clear()
        for ch in channels:
            self.cmu_tracking.signals.pop(ch, None)
        return zeroed


def _post(post: Post) -> int:
    return 1 if post == "start" else 2
