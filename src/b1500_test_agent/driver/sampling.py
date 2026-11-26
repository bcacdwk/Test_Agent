"""Sampling data blocks (``MM 10``) with sampling indices and time stamps: the timestamp parser (blueprint v2 2.5, 2.7
kind ``smu_sampling``; ATV-22).

A sampling measurement returns ``Block1[,Block2]...`` with one block per held sample, ``Block = [Sampling_no,]
Data1[,Data2]...`` in ``MM`` channel order (PG PDF 49, printed 1-29); ``Sampling_no`` (data type ``X``) is present
when ``FMT`` mode is not 0, and with the time stamp function (``TSC 1``) every datum is preceded by its ``Time``
element (data type ``T``, the time from the last ``TSR`` to the start of that measurement; PG PDF 46, printed 1-26).
Data types: Table 1-12, PDF 55.

``parse_sampling`` groups the parsed FMT 1/5 elements (``driver/parser.py``) into ``Sample`` rows by their data type
letters, not by fixed positions, so the same code reads blocks with or without index and time stamps, and a block
whose index jumps (the measurement took longer than the interval, or auto ranging discarded a sample: PDF 49) or a
read cut short by ``AB``. What the manual does not print (TODO(verify)[L5.A3, L5.A9], ATV-22): the status and
channel letters of the ``Sampling_no`` element (ignored here) and whether the index precedes the first time stamp
(accepted either way only in that order: ``X`` opens a block). Values after an automatic abort read ``199.999E+99``
with status ``V`` (``MSC``, PDF 473): ``Sample.dummy``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.parser import MeasurementPoint, MeasurementStatus

INDEX_TYPE = "X"
"""Data type letter of the sampling index (Table 1-12, PDF 55)."""

TIME_TYPE = "T"
"""Data type letter of a time stamp (Table 1-12, PDF 55)."""

VALUE_TYPES = frozenset({"I", "V"})
"""Data types of SMU measurement values (current, voltage)."""


def _canonical(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


@dataclass(frozen=True)
class Sample:
    """One sampling point: the sampling index (``None`` without ``FMT`` mode 1), one time stamp per measured channel
    (``None`` without ``TSC 1``) and one value element per measured channel, in ``MM`` order."""

    index: int | None
    times: tuple[float | None, ...]
    values: tuple[MeasurementPoint, ...]

    @property
    def time(self) -> float | None:
        """The time stamp of the first measured channel (when the sample's measurement started)."""
        return self.times[0] if self.times else None

    @property
    def dummy(self) -> bool:
        """True for a sample after an automatic abort: every value is ``199.999E+99`` with status ``V``."""
        return all(v.invalid and v.status == MeasurementStatus.OVER_RANGE_OR_SWEEP_ABORTED for v in self.values)


@dataclass(frozen=True)
class SamplingData:
    """The parsed samples of one ``MM 10`` read and the elements of an incomplete last sample (``trailing``; a read
    cut short by ``AB`` returns only what was measured before it)."""

    samples: tuple[Sample, ...]
    trailing: int = 0

    @property
    def has_index(self) -> bool:
        """True when the samples carry sampling indices."""
        return any(s.index is not None for s in self.samples)

    @property
    def has_time(self) -> bool:
        """True when the samples carry time stamps."""
        return any(t is not None for s in self.samples for t in s.times)

    @property
    def measured(self) -> tuple[Sample, ...]:
        """The samples before the first dummy (post-abort) sample."""
        out: list[Sample] = []
        for sample in self.samples:
            if sample.dummy:
                break
            out.append(sample)
        return tuple(out)


def _index(point: MeasurementPoint, position: int) -> int:
    value = point.value
    if not math.isfinite(value) or value < 1 or abs(value - round(value)) > 1e-6 * max(1.0, value):
        raise FlexParseError(f"element {position}: sampling index {point.raw!r} is not a positive integer",
                             raw=point.raw)
    return round(value)


def parse_sampling(points: Sequence[MeasurementPoint], measure: Sequence[int]) -> SamplingData:
    """Group the elements of one sampling read into ``Sample`` rows (module docstring).

    ``measure`` is the ``MM 10`` channel list in order. A sample is complete when every measured channel has its
    value; a ``Sampling_no`` element opens a sample, a ``Time`` element belongs to the next value.

    Raises:
        FlexParseError: On source data, an index or time stamp in the wrong place, a value of an unexpected channel
            or data type, or a sampling index that is not a positive integer.
    """
    if not measure:
        raise ValueError("measure needs at least one channel")
    expected = [_canonical(ch) for ch in measure]
    samples: list[Sample] = []
    index: int | None = None
    times: list[float | None] = []
    values: list[MeasurementPoint] = []
    pending_time: float | None = None
    for position, point in enumerate(points):
        if point.is_source:
            raise FlexParseError(f"element {position}: sampling data carry no source data, got {point.raw!r}",
                                 raw=point.raw)
        if point.data_type == INDEX_TYPE:
            if index is not None or values or pending_time is not None:
                raise FlexParseError(f"element {position}: sampling index {point.raw!r} inside a sample",
                                     raw=point.raw)
            index = _index(point, position)
            continue
        if point.data_type == TIME_TYPE:
            if pending_time is not None:
                raise FlexParseError(f"element {position}: two time stamps in a row ({point.raw!r})", raw=point.raw)
            pending_time = point.value
            continue
        slot = len(values)
        channel = point.channel_number
        if point.data_type not in VALUE_TYPES or channel is None or _canonical(channel) != expected[slot]:
            raise FlexParseError(f"element {position}: {point.raw!r} is not the value of channel {measure[slot]} "
                                 "(MM 10 order)", raw=point.raw)
        values.append(point)
        times.append(pending_time)
        pending_time = None
        if len(values) == len(expected):
            samples.append(Sample(index=index, times=tuple(times), values=tuple(values)))
            index, times, values = None, [], []
    trailing = len(values) + (index is not None) + (pending_time is not None) + sum(t is not None for t in times)
    return SamplingData(samples=tuple(samples), trailing=trailing)
