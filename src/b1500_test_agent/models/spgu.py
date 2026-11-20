"""HV-SPGU output programs: what a kind asks the SPGU to output, and the one pulse train per channel the guard and
the plan rules see (blueprint v2 2.5, 2.7 ``spgu_pulse``, 2.8 R-PULSE-01/R-SPGU-01).

Two programs, one per SPGU operation mode (the mode applies to every SPGU of the mainframe):

- ``SpguPulseProgram`` (PG mode): one pulse period for all channels, a run bounded by a pulse ``count`` or an output
  ``duration_s`` (free run cannot be expressed), and per channel a ``SpguChannel``: the ``SER`` load the output level
  is adjusted to, one pulse source (two-level pulse) or both (three-level pulse: the channel outputs the sum of the
  two sources, PG p146 (2-58) "3-level"), the pulse switch and the trigger output.
- ``AlwgProgram`` (ALWG mode, PG p147-151 (2-59)): per channel up to 512 patterns of linear vectors (incremental time,
  level, pulse-switch state), one sequence of ``(pattern number, repeat)`` cycles shared by every channel, a run
  bounded by a sequence ``count`` or a ``duration_s``.

The guard view (``guard_train``) reduces a channel to the single ``PulseTrain`` that ``OutputGuard.check_pulse``
checks at every configure, start and load change, and that a kind puts into its ``SourcePlan`` (so
``models.sources.pulse_envelope`` admits exactly it):

- ``base_v``: the level the channel holds when no pulse runs (PG: ``base1 + base2``; ALWG: the initial level of the
  first pattern of the sequence, which the channel outputs after ``SPUPD`` and ``SPP``);
- ``peak_v``: the set level of largest magnitude the channel can output (three-level: the largest sum of one level
  of each source, the overlap of both pulses included even when their timing excludes it; ALWG: every pattern's
  initial level and every vector level);
- ``width_s``: the time per period away from ``base_v`` (three-level: the union of both pulse windows; ALWG: every
  segment not at ``base_v``, including the 50 ns setup delays that hold such a level);
- ``period_s``: the pulse period (ALWG: the sequence repetition period); ``count``/``duration_s``: the run bound
  (ALWG: sequences); ``load_ohm``: the ``SER`` load.

``source_trains`` lists one ``PulseTrain`` per pulse source with its own delay, width and transition times, for the
module-spec checks (``driver.modules.SPGU_SPEC.train_problems``). The arithmetic of the output time lives here, once:
``output_time_s`` is what ``SPST?`` reads 1 for (count x period, the duration, or count x sequence time + the setup
delays between sequences).
"""

from __future__ import annotations

import itertools
import math
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.sources import PulseTrain

ALWG_SETUP_DELAY_S: Final = 5e-8
"""Delay inserted when the ALWG output changes to a pattern of a different number; the channel holds the last level
of the previous pattern meanwhile (PG p148 (2-60) "50 ns")."""

SpguLevels = Literal["two_level", "three_level"]
"""PG output mode of a pulse channel: one pulse source, or the sum of pulse sources 1 and 2 (PG p511 (4-193))."""

PulseSource = Literal[1, 2]
"""Pulse signal source of an SPGU channel (PG p514 (4-196) "src")."""

AlwgTrigger = Literal[0, 1, 2, 3]
"""ALWG trigger output (PG p523 (4-205) "STGP"): 0 off, 1 sequence start, 2 pattern change, 3 every pattern start;
PG mode uses 0 and 1 (every pulse)."""


class SpguSource(StrictModel):
    """One pulse signal source of a PG channel (PG p514-516 (4-196) Figure 2-31): pulse ``delay_s`` within the period,
    ``width_s``, ``lead_s``/``trail_s`` transition times (initial 20 ns; ``trail_s`` ``None`` = the leading time, as
    ``SPT`` does), ``base_v`` and ``peak_v`` set levels (the output adjusts them to the channel's ``SER`` load)."""

    delay_s: float = Field(default=0.0, ge=0)
    width_s: float = Field(gt=0)
    lead_s: float = Field(default=2e-8, gt=0)
    trail_s: float | None = Field(default=None, gt=0)
    base_v: float
    peak_v: float

    @property
    def trailing_s(self) -> float:
        """The trailing time in effect (the leading time when none is set)."""
        return self.lead_s if self.trail_s is None else self.trail_s

    @property
    def end_s(self) -> float:
        """End of the pulse window within the period (``delay + width``)."""
        return self.delay_s + self.width_s


class PulseSwitch(StrictModel):
    """The channel's pulse switch, enabled (PG p478-479 (4-160) "ODSW"): ``normally_closed`` or normally open; in PG
    mode it changes over ``delay_s`` after each pulse start and holds the switched state for ``width_s`` (initial 0 s
    and 100 ns); in ALWG mode each vector sets it and the timing is ignored. Without a ``PulseSwitch`` the switch is
    disabled (the output is always connected)."""

    normally_closed: bool = False
    delay_s: float = Field(default=0.0, ge=0)
    width_s: float = Field(default=1e-7, gt=0)


class SpguChannel(StrictModel):
    """One PG-mode SPGU channel: ``SER`` ``load_ohm``, the output mode and its pulse sources, the pulse switch and
    whether the module's trigger output follows this channel's pulses."""

    load_ohm: float = Field(gt=0)
    levels: SpguLevels = "two_level"
    sources: dict[PulseSource, SpguSource] = Field(min_length=1, max_length=2)
    pulse_switch: PulseSwitch | None = None
    trigger: bool = False

    @model_validator(mode="after")
    def _sources_fit_the_mode(self) -> SpguChannel:
        if self.levels == "two_level" and len(self.sources) != 1:
            raise ValueError("a two-level channel uses exactly one pulse source (1 or 2)")
        if self.levels == "three_level" and set(self.sources) != {1, 2}:
            raise ValueError("a three-level channel uses pulse sources 1 and 2")
        return self

    @property
    def base_v(self) -> float:
        """Level between pulses: the source's base, or the sum of both bases (three-level)."""
        return math.fsum(s.base_v for s in self.sources.values())

    def level_set(self) -> list[float]:
        """Every level the channel can output: each combination of one level per source (sums for three-level)."""
        levels = [0.0]
        for source in self.sources.values():
            levels = [a + b for a in levels for b in (source.base_v, source.peak_v)]
        return levels

    @property
    def extreme_v(self) -> float:
        """The output level of largest magnitude (first one found on a tie)."""
        return max(self.level_set(), key=abs)

    def windows(self) -> list[tuple[float, float]]:
        """The pulse windows ``(delay, delay + width)`` of the sources, in source order."""
        return [(s.delay_s, s.end_s) for _, s in sorted(self.sources.items())]

    @property
    def away_s(self) -> float:
        """Time per period away from the base level: the union of the pulse windows."""
        total, reach = 0.0, -math.inf
        for start, end in sorted(self.windows()):
            if end > reach:
                total += end - max(start, reach)
                reach = end
        return total


class _Bounded(StrictModel):
    """A run bounded by ``count`` (pulses or sequences) or ``duration_s`` (exactly one; never free run)."""

    count: int | None = Field(default=None, ge=1)
    duration_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one_bound(self) -> _Bounded:
        if (self.count is None) == (self.duration_s is None):
            raise ValueError("an SPGU run has exactly one of count and duration_s (free run is never used)")
        return self


class SpguPulseProgram(_Bounded):
    """A PG-mode SPGU output: ``period_s`` for every channel (``SPPER``), the run bound (``SPRM 1|2``) and the
    channels."""

    period_s: float = Field(gt=0)
    channels: dict[Channel, SpguChannel] = Field(min_length=1)

    @model_validator(mode="after")
    def _windows_fit_the_period(self) -> SpguPulseProgram:
        for ch, channel in self.channels.items():
            for source in channel.sources.values():
                if source.end_s >= self.period_s:
                    raise ValueError(f"channel {ch}: delay + width {source.end_s:g} s must be shorter than the "
                                     f"period {self.period_s:g} s")
        return self

    def output_time_s(self) -> float:
        """How long the output runs (``SPST?`` 1): ``count x period`` or the duration."""
        return self.count * self.period_s if self.count is not None else float(self.duration_s or 0.0)

    def source_trains(self, ch: int) -> list[PulseTrain]:
        """One train per pulse source of channel ``ch`` with its own timing (module-spec checks).

        Raises:
            KeyError: If ``ch`` is not a channel of the program.
        """
        channel = self.channels[ch]
        return [PulseTrain(base_v=s.base_v, peak_v=s.peak_v, width_s=s.width_s, period_s=self.period_s,
                           lead_s=s.lead_s, trail_s=s.trailing_s, delay_s=s.delay_s, count=self.count,
                           duration_s=self.duration_s, load_ohm=channel.load_ohm)
                for _, s in sorted(channel.sources.items())]

    def guard_train(self, ch: int) -> PulseTrain:
        """The guard view of channel ``ch`` (module docstring).

        Raises:
            KeyError: If ``ch`` is not a channel of the program.
        """
        channel = self.channels[ch]
        if channel.levels == "two_level":
            return self.source_trains(ch)[0]
        return PulseTrain(base_v=channel.base_v, peak_v=channel.extreme_v, width_s=channel.away_s,
                          period_s=self.period_s, delay_s=min(s.delay_s for s in channel.sources.values()),
                          count=self.count, duration_s=self.duration_s, load_ohm=channel.load_ohm)

    def trains(self) -> dict[int, list[PulseTrain]]:
        """The guard train of every channel (what a kind puts into ``SourcePlan.pulses``)."""
        return {ch: [self.guard_train(ch)] for ch in self.channels}


# -- ALWG ------------------------------------------------------------------------------------------------------------


class AlwgVector(StrictModel):
    """One ALWG vector (PG p150 (2-62) Table 2-4): a linear ramp over ``dt_s`` (incremental time from the previous
    point) to ``v`` (V), with the pulse switch closed (``switch_closed``) or open during it."""

    dt_s: float = Field(gt=0)
    v: float
    switch_closed: bool = True


class AlwgPattern(StrictModel):
    """One ALWG pattern: its initial level and its vectors (the channel ramps through them in order)."""

    initial_v: float
    vectors: list[AlwgVector] = Field(min_length=1)

    @property
    def duration_s(self) -> float:
        """Time of one pass through the pattern."""
        return math.fsum(v.dt_s for v in self.vectors)

    @property
    def last_v(self) -> float:
        """The level at the end of the pattern."""
        return self.vectors[-1].v

    def levels(self) -> list[float]:
        """The initial level and every vector level."""
        return [self.initial_v, *(v.v for v in self.vectors)]


class AlwgChannel(StrictModel):
    """One ALWG-mode SPGU channel: ``SER`` ``load_ohm``, its patterns (pattern number = list position + 1), whether
    the pulse switch is enabled (``pulse_switch``; each vector then sets its state) and normally closed, and the
    trigger output mode."""

    load_ohm: float = Field(gt=0)
    patterns: list[AlwgPattern] = Field(min_length=1, max_length=512)
    pulse_switch: bool = False
    normally_closed: bool = False
    trigger: AlwgTrigger = 0


AlwgCycle = tuple[Annotated[int, Field(ge=1, le=512)], Annotated[int, Field(ge=1, le=1_048_576)]]
"""One pattern cycle of the ALWG sequence: ``(pattern number, repeat count)`` (PG p151 (2-63) Table 2-5)."""


class AlwgProgram(_Bounded):
    """An ALWG-mode SPGU output: the sequence of pattern cycles shared by every channel, the run bound (``count`` =
    sequences) and the channels with their patterns."""

    sequence: list[AlwgCycle] = Field(min_length=1, max_length=512)
    channels: dict[Channel, AlwgChannel] = Field(min_length=1)

    @model_validator(mode="after")
    def _sequence_resolves(self) -> AlwgProgram:
        for ch, channel in self.channels.items():
            for number, _ in self.sequence:
                if number > len(channel.patterns):
                    raise ValueError(f"channel {ch}: the sequence names pattern {number}, the channel has "
                                     f"{len(channel.patterns)}")
        first = next(iter(self.channels.values()))
        for ch, channel in self.channels.items():
            for number in {n for n, _ in self.sequence}:
                if not math.isclose(channel.patterns[number - 1].duration_s, first.patterns[number - 1].duration_s,
                                    rel_tol=0.0, abs_tol=1e-12):
                    raise ValueError(f"channel {ch}: pattern {number} lasts "
                                     f"{channel.patterns[number - 1].duration_s:g} s, other channels' "
                                     f"{first.patterns[number - 1].duration_s:g} s (the channels run the shared "
                                     "sequence in step)")
        for ch in self.channels:
            train = self._equivalent(ch)
            if train[2] <= 0.0:
                raise ValueError(f"channel {ch}: the ALWG output never leaves its initial level (a constant "
                                 "output is a DC bias; use an SMU)")
            if train[2] >= train[3]:
                raise ValueError(f"channel {ch}: the ALWG output must return to its initial level "
                                 f"{train[0]:g} V for part of every sequence")
        return self

    def _changes(self) -> int:
        """Setup delays inside one sequence (consecutive cycles with different pattern numbers)."""
        numbers = [n for n, _ in self.sequence]
        return sum(1 for a, b in itertools.pairwise(numbers) if a != b)

    @property
    def wraps(self) -> bool:
        """True when a repeated sequence changes pattern from its last cycle to its first (one more setup delay)."""
        return self.sequence[-1][0] != self.sequence[0][0]

    def sequence_time_s(self) -> float:
        """Time of one sequence (the same for every channel: a pattern number lasts equally long on every channel,
        checked at construction): the cycles plus the setup delays inside the sequence."""
        channel = next(iter(self.channels.values()))
        body = math.fsum(repeat * channel.patterns[n - 1].duration_s for n, repeat in self.sequence)
        return body + ALWG_SETUP_DELAY_S * self._changes()

    def repeat_period_s(self) -> float:
        """Time from one sequence start to the next (the sequence plus the wrap-around setup delay)."""
        return self.sequence_time_s() + (ALWG_SETUP_DELAY_S if self.wraps else 0.0)

    def output_time_s(self) -> float:
        """How long the output runs (``SPST?`` 1): ``count`` sequences with the setup delays between them, or the
        duration."""
        if self.count is None:
            return float(self.duration_s or 0.0)
        return self.count * self.sequence_time_s() + (self.count - 1) * (
            ALWG_SETUP_DELAY_S if self.wraps else 0.0)

    def base_v(self, ch: int) -> float:
        """The level channel ``ch`` outputs when idle: the initial level of the sequence's first pattern."""
        return self.channels[ch].patterns[self.sequence[0][0] - 1].initial_v

    def segments(self, ch: int) -> list[tuple[float, float, float, int]]:
        """One sequence of channel ``ch`` as ``(dt, level at start, level at end, repeat)`` segments, the setup
        delays (holding the previous level) included, the wrap-around delay last."""
        patterns = self.channels[ch].patterns
        out: list[tuple[float, float, float, int]] = []
        previous: int | None = None
        held = self.base_v(ch)
        for number, repeat in self.sequence:
            if previous is not None and number != previous:
                out.append((ALWG_SETUP_DELAY_S, held, held, 1))
            pattern = patterns[number - 1]
            level = pattern.initial_v
            for vector in pattern.vectors:
                out.append((vector.dt_s, level, vector.v, repeat))
                level = vector.v
            held, previous = pattern.last_v, number
        if self.wraps:
            out.append((ALWG_SETUP_DELAY_S, held, held, 1))
        return out

    def _equivalent(self, ch: int) -> tuple[float, float, float, float]:
        """``(base, extreme level, time away from base, repetition period)`` of channel ``ch``."""
        base = self.base_v(ch)
        patterns = self.channels[ch].patterns
        levels = [v for number in {n for n, _ in self.sequence} for v in patterns[number - 1].levels()]
        extreme = max(levels, key=abs)
        away = math.fsum(dt * repeat for dt, a, b, repeat in self.segments(ch) if a != base or b != base)
        return base, extreme, away, self.repeat_period_s()

    def guard_train(self, ch: int) -> PulseTrain:
        """The guard view of channel ``ch`` (module docstring).

        Raises:
            KeyError: If ``ch`` is not a channel of the program.
        """
        base, extreme, away, period = self._equivalent(ch)
        return PulseTrain(base_v=base, peak_v=extreme, width_s=away, period_s=period, count=self.count,
                          duration_s=self.duration_s, load_ohm=self.channels[ch].load_ohm)

    def trains(self) -> dict[int, list[PulseTrain]]:
        """The guard train of every channel (what a kind puts into ``SourcePlan.pulses``)."""
        return {ch: [self.guard_train(ch)] for ch in self.channels}


SpguProgram = SpguPulseProgram | AlwgProgram
"""Either SPGU program."""
