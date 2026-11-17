"""ASCII measurement-data formatter of the simulator (FMT 1 and FMT 5).

Written from the Keysight B1500 Series Programming Guide, Edition 15 ("PG"; PDF pages are physical 1-based pages
of ``B1500A Programming Guide.pdf``), independently of ``driver/parser.py`` (no shared code, so a misreading of
the manual is not common-mode):

- Element ``ABCDDDDDDDDDDDD`` for FMT 1/5: A status, B channel, C data type, D 12-character value
  (Table 1-6, PDF 50; element descriptions PDF 51).
- D is ``sn.nnnnnEsnn``, ``snn.nnnnEsnn`` or ``snnn.nnnEsnn`` (PDF 51; Table 4-24 note, PDF 437). The simulator
  writes engineering notation: exponent a multiple of 3, one to three integer digits, six significant digits.
- Source data status ``W`` (first/intermediate step) or ``E`` (last step) (Table 1-7, PDF 52); measurement status
  letters (Table 1-10, PDF 53); channel letters ``A``-``J`` (subchannel 1 of slots 1-10), ``a``-``j`` (subchannel
  2) (Table 1-11, PDF 54); data types ``V`` ``I`` ``T`` ... (Table 1-12, PDF 55).
- Block layout ``Block1[,Block2]...<terminator>``, block = ``[Time,]Data1[,[Time,]Data2]...[,Source_data]``
  (PDF 46, 48); terminator CR/LF for FMT 1 and ``,`` for FMT 5 (Table 4-24, PDF 437; conventions PDF 45).
- Status ``V`` carries the meaningless value ``199.999E+99`` (Table 1-10, PDF 53).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

DUMMY_VALUE = 199.999e99
"""Value sent with status ``V`` (over range, or data after an automatic abort); it has no meaning (PDF 53)."""

MEASUREMENT_STATUS = frozenset("NTCVXFGSUD")
"""Status letters of measurement data (Table 1-10, PDF 53)."""

SOURCE_STATUS = frozenset("WE")
"""Status letters of source data (Table 1-7, PDF 52)."""

DATA_TYPES = frozenset("VIFZYCLRPDQXT")
"""Data type letters ``C`` of FMT 1/5 (Table 1-12, PDF 55)."""

STATUS_SEVERITY = "NGSTCVX"
"""SMU status severity for non-quasi-pulsed measurements, lowest first: N<G<S<T<C<V<X (PDF 51)."""

TERMINATORS = {1: "\r\n", 5: ","}
"""Terminator per supported format (Table 4-24, PDF 437)."""

ELEMENT_WIDTH = 15
"""Characters per FMT 1/5 element: 3 header characters plus the 12-character value (Table 1-6, PDF 50)."""


def worst_status(statuses: Sequence[str]) -> str:
    """The most severe of ``statuses`` (``N`` when empty)."""
    return max(statuses, key=STATUS_SEVERITY.index, default="N")


def channel_letter(channel: int) -> str:
    """Channel code ``B``/``F`` of a PG Table 4-1 channel number (``3`` and ``301`` → ``C``, ``302`` → ``c``)."""
    if 1 <= channel <= 10:
        slot, sub = channel, 1
    else:
        slot, sub = divmod(channel, 100)
    if not (1 <= slot <= 10 and sub in (1, 2)):
        raise ValueError(f"Channel {channel} has no channel letter (PG Table 1-11).")
    return chr((ord("A") if sub == 1 else ord("a")) + slot - 1)


def format_value(value: float) -> str:
    """The 12-character D field: sign, 1-3 integer digits, 5-3 decimals, ``E``, signed 2-digit exponent.

    Engineering notation with six significant digits, e.g. ``+1.23456E-03``, ``-12.3456E-09``, ``+123.456E+00``;
    zero is ``+0.00000E+00``; magnitudes below 1E-99 become zero.
    """
    if not math.isfinite(value):
        raise ValueError(f"Cannot format non-finite value {value!r}.")
    sign = "-" if value < 0 else "+"
    magnitude = abs(value)
    if magnitude < 1e-99:
        return "+0.00000E+00"
    # Round to six significant digits first (this carries 9.999996 into 1.00000e+01), then move the decimal point
    # so the exponent is a multiple of three.
    mantissa, exp_text = f"{magnitude:.5e}".split("e")
    exponent = int(exp_text)
    digits = mantissa.replace(".", "")
    shift = exponent % 3
    exponent -= shift
    if abs(exponent) > 99:
        raise ValueError(f"Value {value!r} is outside the FMT 1/5 exponent range.")
    return f"{sign}{digits[: shift + 1]}.{digits[shift + 1 :]}E{'-' if exponent < 0 else '+'}{abs(exponent):02d}"


@dataclass(frozen=True)
class Element:
    """One data element before formatting: status letter, channel number (or a letter), data type, value."""

    status: str
    channel: int | str
    dtype: str
    value: float

    def text(self) -> str:
        """The 15-character FMT 1/5 element ``ABCDDDDDDDDDDDD``."""
        if self.status not in MEASUREMENT_STATUS | SOURCE_STATUS:
            raise ValueError(f"Unknown status letter {self.status!r}.")
        if self.dtype not in DATA_TYPES:
            raise ValueError(f"Unknown data type {self.dtype!r}.")
        letter = self.channel if isinstance(self.channel, str) else channel_letter(self.channel)
        if len(letter) != 1:
            raise ValueError(f"Channel code {letter!r} is not one character.")
        value = DUMMY_VALUE if self.status == "V" else self.value
        return f"{self.status}{letter}{self.dtype}{format_value(value)}"


def terminator(fmt: int) -> str:
    """Terminator of data output format ``fmt`` (1 or 5)."""
    try:
        return TERMINATORS[fmt]
    except KeyError:
        raise ValueError(f"The simulator formats FMT 1 and FMT 5 only, not FMT {fmt}.") from None


def frame(texts: Sequence[str], fmt: int) -> str:
    """Wire text of a measurement-data message: elements joined by ``,`` plus the format's terminator."""
    return ",".join(texts) + terminator(fmt)


def format_elements(elements: Sequence[Element], fmt: int) -> str:
    """Wire text of ``elements`` (blocks already flattened in output order) in format ``fmt``."""
    return frame([e.text() for e in elements], fmt)
