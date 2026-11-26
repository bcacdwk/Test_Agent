"""Quasi-static C-V data (``MM 13``): the parser support of kind ``smu_qscv`` (blueprint v2 2.5, 2.7; WP8.5).

A QSCV sweep returns one block per measured step (PG p49 (1-29)): ``[DataL,] DataC [,Source_data]`` with ``FMT 1,1``
(``Source_data`` on), the leakage current ``DataL`` (data type ``I``) only with ``QSL 1,x``. Elements are FMT 1/5
elements (``driver/parser.py``). The PG example (Table 3-17, p243-245 (3-63 to 3-65)) prints the data types: ``C`` for
the capacitance, ``I`` for the leakage (``NCC``/``NCI`` headers on the measurement channel), ``V`` with ``W``/``E`` for
the sweep output. ``QSZ 2`` returns one ``C`` datum, the measured offset (p499 (4-181)).

Status letters (Table 1-10, PG p53 (1-33)): ``N`` normal, ``C`` this channel's compliance, ``T`` another channel's,
``V`` over range or data after an automatic abort (``199.999E+99``, ``QSM 2``; error 242), ``X`` oscillation.

What the manual does not print (TODO(verify)[L6.A6, L6.A8], real blocks): the channel letter of
``DataL``/``DataC`` (assumed: the ``MM 13`` measurement channel, as the example's ``C`` channel letter is its gate SMU)
and the number of blocks of a double sweep (assumed: every step of both directions, turning point not measured).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.parser import MeasurementPoint


def _canonical(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


@dataclass(frozen=True)
class QscvStep:
    """One parsed QSCV block: ``capacitance`` (DataC), ``leakage`` (DataL, ``None`` without ``QSL 1,x``) and
    ``source`` (Source_data: the step voltage the sweep source reports)."""

    capacitance: MeasurementPoint
    leakage: MeasurementPoint | None
    source: MeasurementPoint

    @property
    def status(self) -> str:
        """The capacitance datum's status letter."""
        return str(self.capacitance.status.value)


def _expect(point: MeasurementPoint, position: int, channel: int, data_type: str, what: str, *,
            source: bool = False) -> MeasurementPoint:
    number = point.channel_number
    if (point.is_source != source or number is None or _canonical(number) != _canonical(channel)
            or point.data_type != data_type):
        raise FlexParseError(f"element {position}: {point.raw!r} is not {what} ({data_type} of channel {channel})",
                             raw=point.raw)
    return point


def parse_qscv(points: Sequence[MeasurementPoint], *, channel: int, source_channel: int, leakage: bool,
               steps: int) -> list[QscvStep]:
    """The ``steps`` blocks of one QSCV read (module docstring): ``[DataL,] DataC, Source_data`` per step.

    Raises:
        FlexParseError: On another number of elements, a misplaced source element, or an element of another channel
            or data type than expected.
    """
    width = 3 if leakage else 2
    if len(points) != steps * width:
        raise FlexParseError(f"a QSCV sweep of {steps} steps returns {steps * width} elements "
                             f"({'DataL,' if leakage else ''}DataC,Source_data per step), got {len(points)}",
                             raw=",".join(p.raw for p in points))
    out: list[QscvStep] = []
    for k in range(steps):
        block = points[k * width:(k + 1) * width]
        base = k * width
        leak = _expect(block[0], base, channel, "I", "DataL") if leakage else None
        cap = _expect(block[width - 2], base + width - 2, channel, "C", "DataC")
        src = _expect(block[width - 1], base + width - 1, source_channel, "V", "Source_data", source=True)
        out.append(QscvStep(capacitance=cap, leakage=leak, source=src))
    return out


def parse_qscv_offset(points: Sequence[MeasurementPoint], *, channel: int) -> MeasurementPoint:
    """The one ``C`` datum of a ``QSZ 2`` offset measurement on ``channel``.

    Raises:
        FlexParseError: On another number of elements or an element of another channel or data type.
    """
    if len(points) != 1:
        raise FlexParseError(f"a QSCV offset measurement returns one element, got {len(points)}",
                             raw=",".join(p.raw for p in points))
    return _expect(points[0], 0, channel, "C", "the QSCV offset")


__all__ = ["QscvStep", "parse_qscv", "parse_qscv_offset"]
