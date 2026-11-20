"""Pulse trains and WGFMU waveform programs: the typed part of a kind's compiled program that the plan rules, the
``OutputGuard`` and the plan summary read (blueprint v2 2.3, 2.5, 2.7.1, 2.8, 2.9).

A kind that drives a pulse source (HV-SPGU, SMU pulse) or a WGFMU stores a ``SourcePlan`` in its compiled program
under ``SOURCE_PLAN_KEY`` (``plan.program["sources"]``, hashed with the rest of the program; ``source_plan()`` reads
it back):

- ``pulses``: per channel, the nominal pulse trains the kind starts (``PulseTrain``: base and peak level, width,
  period, transition times, count or duration, the SPGU ``SER`` load, how often the plan repeats the train).
  R-PULSE-01 checks their timing against the module spec, R-PULSE-02/03 and R-SPGU-01 their levels and totals
  against the DUT profile and the policy; ``pulse_envelope()`` derives the ``PulseEnvelope`` the guard enforces.
- ``waveform``: the WGFMU ``WaveformProgram`` (channel setups, patterns of ``(dt, v)`` vectors, measure and range
  events, per-channel sequences) that R-WG-02 checks against the module limits and the policy and that the WGFMU
  driver loads (the builders of ``catalog/waveforms.py`` produce it).
- ``stress``/``schedule`` (WP7.6, kind ``stress_measure``): the DC level each channel holds during the stress and the
  recovery (``DcStress``) and the stress schedule (``StressSchedule``: total stress and recovery hold times, number of
  reads). The levels lie inside the channel envelope already (the guard enforces it); the plan summary shows them so
  that the human confirms the stress itself, not only the envelope.

Arithmetic shared by the rules, the guard and the kinds (one function each, so they can never disagree):

- ``open_load_voltage``: a source with output resistance ``R`` whose level is adjusted to a declared load (HV-SPGU
  ``SER``) puts ``|V| (load + R) / load`` on an open load, i.e. twice the set level at ``SER`` = 50 Ohm (UG p76
  (2-36) "50", PG p507 (4-189) "SER"); a source whose set level is the open-load level (SMU pulse, WGFMU) puts ``|V|``.
- WGFMU program timing: a channel repeats a pattern without delay, but 50 ns pass between different sequences (WG
  p80 (4-10) "50 ns"); a measurement event ends at ``t + interval (points - 1) + average`` (+10 ns when the average
  is 0; WG p125 (4-55) "eventEndTime"); RAW events return ``points (1 + int(average / 5 ns))`` values, AVERAGED events
  ``points``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from b1500_test_agent.models.common import StrictModel
from b1500_test_agent.models.measurement import Channel
from b1500_test_agent.models.plan import PulseEnvelope

SOURCE_PLAN_KEY: Final = "sources"
"""Key of the ``SourcePlan`` in ``PlanRecord.program``."""

WGFMU_GRID_S: Final = 1e-8
"""WGFMU time resolution: vectors, event times, intervals and averages lie on a 10 ns grid."""

WGFMU_SEQUENCE_GAP_S: Final = 5e-8
"""Delay between two different sequences of one channel (10 ns last level + 40 ns next initial level)."""

WGFMU_RAW_SAMPLE_S: Final = 5e-9
"""Internal sampling period of an averaged measurement; RAW data return every 5 ns sample."""

WGFMU_EVENT_TAIL_S: Final = 1e-8
"""Added to a measurement event's end time when its average is 0."""

_GRID_TOL: Final = 1e-6
"""Relative tolerance (of the grid step) for 'lies on the grid' (floating-point representation only)."""


def on_grid(value: float, step: float) -> bool:
    """True when ``value`` is an integer multiple of ``step`` (up to floating-point representation)."""
    if step <= 0 or not math.isfinite(value):
        return False
    return abs(value - round(value / step) * step) <= _GRID_TOL * step


def open_load_voltage(max_abs_set_v: float, *, load_ohm: float | None, source_ohm: float | None) -> float:
    """|V| an open load sees for a set level of ``max_abs_set_v``.

    ``source_ohm``: output resistance of a source whose level is adjusted to ``load_ohm`` (HV-SPGU: 50 Ohm; without
    ``load_ohm`` the source's initial ``SER`` equals its output resistance, the 2x worst case). ``None`` for sources
    whose set level is the open-load level (SMU pulse, WGFMU): the result is the set level.
    """
    level = abs(max_abs_set_v)
    if source_ohm is None:
        return level
    load = source_ohm if load_ohm is None else load_ohm
    return level * (load + source_ohm) / load


def short_circuit_current(open_v: float, *, source_ohm: float, series_ohm: float = 0.0) -> float:
    """Current into a short behind ``series_ohm``: ``V_open / (source_ohm + series_ohm)``."""
    return abs(open_v) / (source_ohm + max(series_ohm, 0.0))


# -- Pulse trains ----------------------------------------------------------------------------------------------------


class PulseTrain(StrictModel):
    """One nominal pulse train of a pulse role: what the kind programs and starts (``SPV``/``SPT``/``SPPER``/``SPRM``
    on the HV-SPGU, ``PT``/``PV`` on an SMU, a pattern on the WGFMU).

    ``base_v``/``peak_v``: set levels (V). ``width_s``/``period_s``: pulse width and period. ``lead_s``/``trail_s``:
    transition times (``None`` = the module's initial value; SMU pulses have none). ``delay_s``: pulse delay within the
    period. Exactly one of ``count`` (pulses per start) and ``duration_s`` (output time per start) bounds the train: a
    free-running output cannot be expressed. ``repeat``: how many times the plan starts this train (cycles, grid
    points). ``load_ohm``: the HV-SPGU ``SER`` load the output level is adjusted to (R-SPGU-01).
    """

    base_v: float
    peak_v: float
    width_s: float = Field(gt=0)
    period_s: float = Field(gt=0)
    lead_s: float | None = Field(default=None, gt=0)
    trail_s: float | None = Field(default=None, gt=0)
    delay_s: float = Field(default=0.0, ge=0)
    count: int | None = Field(default=None, ge=1)
    duration_s: float | None = Field(default=None, gt=0)
    repeat: int = Field(default=1, ge=1)
    load_ohm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _bounded(self) -> PulseTrain:
        if (self.count is None) == (self.duration_s is None):
            raise ValueError("A pulse train has exactly one of count and duration_s (never free-run).")
        if self.width_s >= self.period_s:
            raise ValueError("width_s must be shorter than period_s.")
        return self

    @property
    def max_abs_set_v(self) -> float:
        """Largest |set level| (base or peak)."""
        return max(abs(self.base_v), abs(self.peak_v))

    @property
    def pulses(self) -> int:
        """Pulses per start (``count``, or the periods that begin within ``duration_s``)."""
        if self.count is not None:
            return self.count
        assert self.duration_s is not None
        return max(1, math.ceil(self.duration_s / self.period_s - 1e-9))

    @property
    def total_pulses(self) -> int:
        """Pulses over the whole plan (``pulses x repeat``)."""
        return self.pulses * self.repeat

    @property
    def duty(self) -> float:
        """``width / period``."""
        return self.width_s / self.period_s

    @property
    def on_time_s(self) -> float:
        """Time at the pulse level per start (``pulses x width``)."""
        return self.pulses * self.width_s

    @property
    def total_on_time_s(self) -> float:
        """Time at the pulse level over the whole plan."""
        return self.on_time_s * self.repeat

    def open_load_v(self, *, source_ohm: float | None) -> float:
        """|V| an open load sees (``open_load_voltage`` with this train's ``load_ohm``)."""
        return open_load_voltage(self.max_abs_set_v, load_ohm=self.load_ohm, source_ohm=source_ohm)


def pulse_envelope(trains: Sequence[PulseTrain], *, source_ohm: float | None,
                   short_circuit_a: float | None = None) -> PulseEnvelope:
    """The ``PulseEnvelope`` that admits every train of one channel (what a kind puts on the channel envelope).

    ``max_count`` and ``max_on_time_s`` bound one started train (``OutputGuard.check_pulse`` checks one train per
    call); the plan totals (``repeat``) are bounded by the plan rules. ``max_short_circuit_a`` is the DUT-independent
    worst case ``V_open / source_ohm`` (a short at the output); without ``source_ohm`` it is ``short_circuit_a`` (or 0
    for an SMU pulse, whose compliance bounds the current).

    Raises:
        ValueError: If ``trains`` is empty.
    """
    if not trains:
        raise ValueError("a pulse envelope needs at least one pulse train")
    v_dut = max(t.open_load_v(source_ohm=source_ohm) for t in trains)
    if source_ohm is not None:
        isc = short_circuit_current(v_dut, source_ohm=source_ohm)
    else:
        isc = short_circuit_a if short_circuit_a is not None else 0.0
    return PulseEnvelope(
        max_abs_v_dut=v_dut,
        min_width_s=min(t.width_s for t in trains),
        max_width_s=max(t.width_s for t in trains),
        max_duty=max(t.duty for t in trains),
        max_count=max(t.pulses for t in trains),
        max_on_time_s=max(t.on_time_s for t in trains),
        max_short_circuit_a=isc,
    )


# -- WGFMU waveform program ------------------------------------------------------------------------------------------

WgfmuMode = Literal["dc", "fastiv", "pg", "smu"]
"""WGFMU operation mode (``WGFMU_setOperationMode``): DC, Fast IV, PG or SMU pass-through."""

WgfmuForceRange = Literal["auto", "3v", "5v", "-10v", "10v"]
"""WGFMU force voltage range (``WGFMU_setForceVoltageRange``): auto, -3..3, -5..5, -10..0, 0..10 V."""

WgfmuCurrentRange = Literal["1ua", "10ua", "100ua", "1ma", "10ma"]
"""WGFMU current measurement range (``WGFMU_setMeasureCurrentRange``, range events)."""

WgfmuVoltageRange = Literal["5v", "10v"]
"""WGFMU voltage measurement range (``WGFMU_setMeasureVoltageRange``)."""


class ChannelSetup(StrictModel):
    """Setup of one WGFMU channel: operation mode, force range, what it measures and in which range."""

    mode: WgfmuMode
    force_range: WgfmuForceRange = "auto"
    measure: Literal["voltage", "current"] = "voltage"
    current_range: WgfmuCurrentRange | None = None
    voltage_range: WgfmuVoltageRange | None = None
    measure_enabled: bool = True


class Pattern(StrictModel):
    """A waveform pattern: initial level ``v0`` and ``(dt, v)`` vectors (``dt`` incremental, linear ramps)."""

    v0: float
    vectors: list[tuple[float, float]] = Field(default_factory=list)

    @property
    def duration_s(self) -> float:
        """Total time of the pattern (sum of the vector times)."""
        return math.fsum(dt for dt, _ in self.vectors)

    def levels(self) -> list[float]:
        """Every level of the pattern, ``v0`` first."""
        return [self.v0, *(v for _, v in self.vectors)]


class MeasureEvent(StrictModel):
    """A sampling measurement while a pattern is output (``WGFMU_setMeasureEvent``)."""

    kind: Literal["measure"] = "measure"
    pattern: str = Field(min_length=1)
    event: str = Field(min_length=1)
    t: float = Field(ge=0)
    points: int = Field(ge=1)
    interval: float = Field(gt=0)
    average: float = Field(default=0.0, ge=0)
    raw: bool = False

    @property
    def end_s(self) -> float:
        """Event end time from the pattern origin (``t + interval (points - 1) + average``, +10 ns if average 0)."""
        tail = self.average if self.average > 0 else WGFMU_EVENT_TAIL_S
        return self.t + self.interval * (self.points - 1) + tail

    @property
    def data_points(self) -> int:
        """Values the event returns: ``points`` (AVERAGED) or ``points (1 + int(average / 5 ns))`` (RAW)."""
        if not self.raw:
            return self.points
        return self.points * (1 + int(self.average / WGFMU_RAW_SAMPLE_S + 1e-9))


class RangeEvent(StrictModel):
    """A current-range change while a pattern is output (``WGFMU_setRangeEvent``; Fast IV current only)."""

    kind: Literal["range"] = "range"
    pattern: str = Field(min_length=1)
    event: str = Field(min_length=1)
    t: float = Field(ge=0)
    range: WgfmuCurrentRange


WaveformEvent = Annotated[MeasureEvent | RangeEvent, Field(discriminator="kind")]


class WaveformProgram(StrictModel):
    """One WGFMU waveform program (blueprint v2 2.7.1): what ``WgfmuDriver.load`` sets up and ``run`` executes.

    ``builder``: the builder that produced it (``pulse_train``, ``dc_sample``, ``table`` ...; shown in the summary).
    ``channels``: setup per WGFMU channel. ``patterns``: by name. ``events``: measure and range events, each naming
    its pattern. ``sequences``: per channel, ``(pattern, count)`` in output order. Every sequence channel has a setup,
    every sequence and event names an existing pattern; the limits (vectors, sequences, points, grid, event rules)
    are checked by R-WG-02, not here.
    """

    builder: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    channels: dict[Channel, ChannelSetup] = Field(min_length=1)
    patterns: dict[str, Pattern] = Field(min_length=1)
    events: list[WaveformEvent] = Field(default_factory=list)
    sequences: dict[Channel, list[tuple[str, float]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references_resolve(self) -> WaveformProgram:
        for ch, items in self.sequences.items():
            if ch not in self.channels:
                raise ValueError(f"sequence channel {ch} has no channel setup")
            for name, _ in items:
                if name not in self.patterns:
                    raise ValueError(f"sequence of channel {ch} names an unknown pattern {name!r}")
        for event in self.events:
            if event.pattern not in self.patterns:
                raise ValueError(f"event {event.event!r} names an unknown pattern {event.pattern!r}")
        return self

    def channel_patterns(self, ch: int) -> list[str]:
        """Names of the patterns channel ``ch`` outputs, in first-use order."""
        names: list[str] = []
        for name, _ in self.sequences.get(ch, []):
            if name not in names:
                names.append(name)
        return names

    def sequence_time_s(self, ch: int) -> float:
        """Output time of channel ``ch``: sum of ``count x pattern time`` plus 50 ns between sequences."""
        items = self.sequences.get(ch, [])
        body = math.fsum(round(count) * self.patterns[name].duration_s for name, count in items)
        return body + WGFMU_SEQUENCE_GAP_S * max(len(items) - 1, 0)

    def total_time_s(self) -> float:
        """Longest channel output time (channels start together)."""
        return max((self.sequence_time_s(ch) for ch in self.sequences), default=0.0)

    def measure_events(self, pattern: str) -> list[MeasureEvent]:
        return [e for e in self.events if isinstance(e, MeasureEvent) and e.pattern == pattern]

    def range_events(self, pattern: str) -> list[RangeEvent]:
        return [e for e in self.events if isinstance(e, RangeEvent) and e.pattern == pattern]

    def points(self, ch: int) -> int:
        """Values channel ``ch`` stores over the run (every sequence repeat of every measure event)."""
        total = 0
        for name, count in self.sequences.get(ch, []):
            total += round(count) * sum(e.data_points for e in self.measure_events(name))
        return total

    def levels(self, ch: int) -> list[float]:
        """Every level channel ``ch`` outputs (``v0`` and vector levels of its patterns)."""
        return [v for name in self.channel_patterns(ch) for v in self.patterns[name].levels()]

    def intervals(self, ch: int) -> list[float]:
        """Sampling intervals of the measure events of channel ``ch``'s patterns."""
        return [e.interval for name in self.channel_patterns(ch) for e in self.measure_events(name)]

    def preview(self) -> list[str]:
        """Human-readable lines: channel setups, patterns, events and sequences (for ``validate_plan``)."""
        lines = [f"builder {self.builder}"]
        for ch, setup in sorted(self.channels.items()):
            rng = setup.current_range if setup.measure == "current" else setup.voltage_range
            lines.append(f"ch {ch}: {setup.mode} force {setup.force_range} measure {setup.measure}"
                         + (f" {rng}" if rng else "") + ("" if setup.measure_enabled else " (disabled)"))
        for name, pattern in self.patterns.items():
            levels = pattern.levels()
            lines.append(f"pattern {name}: v0 {pattern.v0:g} V, {len(pattern.vectors)} vectors, "
                         f"{pattern.duration_s:.6g} s, levels {min(levels):g}..{max(levels):g} V")
        for event in self.events:
            if isinstance(event, MeasureEvent):
                lines.append(f"measure {event.event} @{event.pattern}: t {event.t:.6g} s, {event.points} pts every "
                             f"{event.interval:.6g} s, average {event.average:.6g} s"
                             + (" raw" if event.raw else ""))
            else:
                lines.append(f"range {event.event} @{event.pattern}: t {event.t:.6g} s -> {event.range}")
        for ch, items in sorted(self.sequences.items()):
            lines.append(f"sequence {ch}: " + ", ".join(f"{name} x{round(count)}" for name, count in items))
        return lines


# -- Source plan -----------------------------------------------------------------------------------------------------


class DcStress(StrictModel):
    """The DC levels a channel holds during the stress and the recovery holds of a stress-measure plan (V)."""

    level_v: float
    recovery_v: float = 0.0


class StressSchedule(StrictModel):
    """A stress-measure schedule: total stress and recovery hold times (s) and the reads after the reference read."""

    stress_s: float = Field(gt=0)
    reads: int = Field(ge=1)
    recovery_s: float = Field(default=0.0, ge=0)
    recovery_reads: int = Field(default=0, ge=0)


class SourcePlan(StrictModel):
    """The typed source part of a kind's program (``plan.program["sources"]``): pulse trains per channel, the
    WGFMU waveform program and the DC stress of a stress-measure plan."""

    pulses: dict[Channel, list[PulseTrain]] = Field(default_factory=dict)
    waveform: WaveformProgram | None = None
    stress: dict[Channel, DcStress] = Field(default_factory=dict)
    schedule: StressSchedule | None = None

    def dc_stress(self, ch: int) -> DcStress | None:
        """The DC stress of channel ``ch`` (``None`` when it holds none)."""
        key = _norm(ch)
        return next((s for own, s in self.stress.items() if _norm(own) == key), None)

    def trains(self, ch: int) -> list[PulseTrain]:
        """The pulse trains of channel ``ch`` (``1`` and ``101`` are the same channel, PG Table 4-1)."""
        key = _norm(ch)
        return [t for own, trains in self.pulses.items() if _norm(own) == key for t in trains]


def _norm(ch: int) -> int:
    return ch * 100 + 1 if 1 <= ch <= 10 else ch


def source_plan(program: Mapping[str, object]) -> SourcePlan:
    """The ``SourcePlan`` stored in a kind's program (empty when the kind stores none).

    Raises:
        pydantic.ValidationError: If the stored value does not validate.
    """
    raw = program.get(SOURCE_PLAN_KEY)
    return SourcePlan() if raw is None else SourcePlan.model_validate(raw)


def total_pulses(trains: Iterable[PulseTrain]) -> int:
    """Pulses over the whole plan for ``trains``."""
    return sum(t.total_pulses for t in trains)


def total_on_time_s(trains: Iterable[PulseTrain]) -> float:
    """Time at the pulse level over the whole plan for ``trains``."""
    return math.fsum(t.total_on_time_s for t in trains)
