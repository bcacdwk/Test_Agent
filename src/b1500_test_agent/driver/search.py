"""Search and quasi-pulsed data (``MM 14``, ``MM 15``, ``MM 9``): the parser support of kind ``smu_search`` (blueprint
v2 2.5, 2.7; WP7.5).

A linear or binary search returns one ``Data_search[,Data_sense]`` (PG p47, printed 1-27): ``Data_search`` is the
value the search source forced at the measurement point closest to the target, ``Data_sense`` (with ``LSVM 1`` /
``BSVM 1``) the monitor channel's reading there. A quasi-pulsed spot measurement returns one ``Data`` of the
measurement channel. Elements are FMT 1/5 elements (``driver/parser.py``); their status letters carry the search
result (Table 1-10, PG p53, printed 1-33; ``EEE`` 16 and 32 of Table 1-8, p52, in FMT 21/25):

- ``Data_search`` ``N`` (found), ``G`` (target not found within the search range: the source value is returned),
  ``S`` (search stopped by the automatic abort: see ``Data_sense``'s status, ``C``/``T``/``V``/``X``);
- quasi-pulsed ``C`` (the source reached its compliance: the breakdown condition of the device), ``N`` (the source
  reached the stop value), ``S`` (slew rate too slow for settling detection, or compliance before a 10 V change from
  start), ``G`` (detection time over 3 s short / 12 s long); severity N<T<C<V<X<G|S
  (``parser.QUASI_PULSED_SPOT_STATUS_SEVERITY``).

What the manual does not print (``TODO(verify)`` at bring-up stage L5/L9, real blocks): the channel letter and the
data type letter of ``Data_search`` (assumed: the search source's channel and the quantity it forces, ``V``/``I``,
as the Table 3-11 example reads it with ``Mid(mret, 4, 12)``, PG p221) and its status on a normal end (assumed
``N``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.parser import MeasurementPoint, MeasurementStatus

FOUND = MeasurementStatus.NORMAL
NOT_FOUND = MeasurementStatus.SEARCH_NOT_FOUND_OR_DETECTION_TIMEOUT
STOPPED = MeasurementStatus.SEARCH_STOPPED_OR_SETTLING_UNDETECTED


def _canonical(channel: int) -> int:
    """PG Table 4-1: channel ``n`` (1-10) and ``n*100+1`` address the same subchannel."""
    return channel * 100 + 1 if 1 <= channel <= 10 else channel


@dataclass(frozen=True)
class SearchData:
    """One parsed search result: ``search`` (``Data_search``) and ``sense`` (``Data_sense``, ``None`` without
    ``LSVM 1``/``BSVM 1``)."""

    search: MeasurementPoint
    sense: MeasurementPoint | None

    @property
    def status(self) -> str:
        """The status letter of ``Data_search``."""
        return str(self.search.status.value)

    @property
    def found(self) -> bool:
        """True when the search ended normally at the target (``N``)."""
        return self.search.status == FOUND

    @property
    def not_found(self) -> bool:
        """True for status ``G``: the target was not found within the search range."""
        return self.search.status == NOT_FOUND

    @property
    def stopped(self) -> bool:
        """True for status ``S``: the automatic abort stopped the search (see ``sense``'s status)."""
        return self.search.status == STOPPED


def _expect(point: MeasurementPoint, position: int, channel: int, quantity: str, what: str) -> MeasurementPoint:
    number = point.channel_number
    if point.is_source or number is None or _canonical(number) != _canonical(channel) or point.data_type != quantity:
        raise FlexParseError(f"element {position}: {point.raw!r} is not {what} ({quantity} of channel {channel})",
                             raw=point.raw)
    return point


def parse_search(points: Sequence[MeasurementPoint], *, source_channel: int, source_quantity: Literal["V", "I"],
                 monitor_channel: int | None = None, monitor_quantity: Literal["V", "I"] | None = None) -> SearchData:
    """``Data_search[,Data_sense]`` of one linear or binary search read (module docstring). Without
    ``monitor_channel`` exactly one element (``LSVM 0``/``BSVM 0``) is expected.

    Raises:
        FlexParseError: On another number of elements, source data (``W``/``E``), or an element of another channel
            or data type than expected.
    """
    sense = monitor_channel is not None
    if sense and monitor_quantity is None:
        raise ValueError("monitor_quantity is required with monitor_channel")
    expected = 2 if sense else 1
    if len(points) != expected:
        raw = ",".join(p.raw for p in points)
        raise FlexParseError(f"a search returns {expected} element(s) (Data_search{',Data_sense' if sense else ''}), "
                             f"got {len(points)}", raw=raw)
    search = _expect(points[0], 0, source_channel, source_quantity, "Data_search")
    if not sense:
        return SearchData(search=search, sense=None)
    assert monitor_channel is not None and monitor_quantity is not None
    return SearchData(search=search, sense=_expect(points[1], 1, monitor_channel, monitor_quantity, "Data_sense"))


def parse_quasi_pulsed(points: Sequence[MeasurementPoint], *, channel: int,
                       quantity: Literal["V", "I"]) -> MeasurementPoint:
    """The one ``Data`` element of a quasi-pulsed spot read (PG p47): ``quantity`` of the measurement ``channel``.

    Raises:
        FlexParseError: On another number of elements or an element of another channel or data type.
    """
    if len(points) != 1:
        raise FlexParseError(f"a quasi-pulsed spot measurement returns one element, got {len(points)}",
                             raw=",".join(p.raw for p in points))
    return _expect(points[0], 0, channel, quantity, "the quasi-pulsed reading")


__all__ = ["FOUND", "NOT_FOUND", "STOPPED", "SearchData", "parse_quasi_pulsed", "parse_search"]
