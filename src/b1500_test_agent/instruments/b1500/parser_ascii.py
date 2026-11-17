"""ASCII measurement data codes and parsers for B1500A FLEX output.

Code tables follow the Keysight B1500 Series Programming Guide, Edition 15:

- "Data Output Format", Tables 1-6 to 1-12 (printed 1-30 to 1-35, PDF pages 50-55).
- ``FMT`` command, Table 4-24 (printed 4-119, PDF page 437).

PDF page numbers are physical 1-based pages of ``B1500A Programming Guide.pdf``.
"""

from dataclasses import dataclass
from enum import IntFlag, StrEnum
from typing import Literal

ModuleKind = Literal["smu", "cmu"]
StatusField = Literal["letter", "eee", "binary", "none"]
DataEncoding = Literal["ascii", "binary_4byte", "binary_8byte"]
Terminator = Literal["crlf_eoi", "eoi", "comma"]

INVALID_DATA_VALUE = 199.999e99
"""Data value returned with status ``V``; it has no meaning (Table 1-10)."""

EXTRANEOUS_DATA_CHANNEL = "Z"
"""Channel code for extraneous data: ``TSQ`` response or invalid data (Table 1-11)."""

INVALID_DATA_TYPE = "z"
"""Data type code ``G`` for invalid data in FMT 21/25 (Table 1-12)."""


class MeasurementStatus(StrEnum):
    """One-character status ``A`` of measurement data (Table 1-10).

    Reported by the ASCII formats with a letter header: FMT 1, 5, 11, and 15.
    FMT 21 and 25 report a three-digit summed code instead; see ``SmuStatus`` and
    ``CmuStatus``. ``W``/``E`` mark source data, not measurement data; see
    ``SourceDataStatus``.
    """

    NORMAL = "N"
    # Another channel reached its compliance setting.
    OTHER_COMPLIANCE = "T"
    # This channel reached its compliance setting.
    COMPLIANCE = "C"
    # Data is over the measurement range, or the sweep was aborted by the automatic
    # stop function or power compliance. Data is INVALID_DATA_VALUE (no meaning).
    OVER_RANGE_OR_SWEEP_ABORTED = "V"
    # One or more channels are oscillating, or source output did not settle before
    # the measurement.
    OSCILLATION_OR_NOT_SETTLED = "X"
    # SMU is in the force saturation condition.
    FORCE_SATURATION = "F"
    # Linear/binary search: target not found within the search range (data is the
    # source output value). Quasi-pulsed spot: detection time over the limit.
    SEARCH_NOT_FOUND_OR_DETECTION_TIMEOUT = "G"
    # Linear/binary search: search stopped (data is the source output value).
    # Quasi-pulsed spot: slew rate too slow for settling detection, or the source
    # reached current compliance before the output changed 10 V from the start.
    SEARCH_STOPPED_OR_SETTLING_UNDETECTED = "S"
    # CMU is in the NULL loop unbalance condition.
    CMU_NULL_LOOP_UNBALANCE = "U"
    # CMU is in the IV amplifier saturation condition.
    CMU_IV_AMP_SATURATION = "D"


class SourceDataStatus(StrEnum):
    """Status of ``Source_data`` (Table 1-7). Severity is ``W`` < ``E``."""

    FIRST_OR_INTERMEDIATE_STEP = "W"
    LAST_STEP = "E"


class SmuStatus(IntFlag):
    """Three-digit summed SMU status ``EEE`` for FMT 21/25 (Table 1-8)."""

    NORMAL = 0
    ADC_OVERFLOW = 1
    OSCILLATION_OR_FORCE_SATURATION = 2
    OTHER_COMPLIANCE = 4
    COMPLIANCE = 8
    SEARCH_TARGET_NOT_FOUND = 16
    SEARCH_STOPPED = 32
    INVALID_DATA = 64
    END_OF_DATA = 128


class CmuStatus(IntFlag):
    """Three-digit summed CMU status ``EEE`` for FMT 21/25 (Table 1-9).

    Values 8, 16, and 32 are not assigned for the CMU.
    """

    NORMAL = 0
    ADC_OVERFLOW = 1
    NULL_LOOP_UNBALANCE = 2
    IV_AMP_SATURATION = 4
    INVALID_DATA = 64
    END_OF_DATA = 128


SMU_STATUS_SEVERITY: tuple[MeasurementStatus, ...] = (
    MeasurementStatus.NORMAL,
    MeasurementStatus.SEARCH_NOT_FOUND_OR_DETECTION_TIMEOUT,
    MeasurementStatus.SEARCH_STOPPED_OR_SETTLING_UNDETECTED,
    MeasurementStatus.OTHER_COMPLIANCE,
    MeasurementStatus.COMPLIANCE,
    MeasurementStatus.OVER_RANGE_OR_SWEEP_ABORTED,
    MeasurementStatus.OSCILLATION_OR_NOT_SETTLED,
)
"""SMU status severity, lowest first, for all but quasi-pulsed spot: N<G<S<T<C<V<X."""

QUASI_PULSED_SPOT_STATUS_SEVERITY: tuple[MeasurementStatus, ...] = (
    MeasurementStatus.NORMAL,
    MeasurementStatus.OTHER_COMPLIANCE,
    MeasurementStatus.COMPLIANCE,
    MeasurementStatus.OVER_RANGE_OR_SWEEP_ABORTED,
    MeasurementStatus.OSCILLATION_OR_NOT_SETTLED,
    MeasurementStatus.SEARCH_NOT_FOUND_OR_DETECTION_TIMEOUT,
    MeasurementStatus.SEARCH_STOPPED_OR_SETTLING_UNDETECTED,
)
"""SMU severity for quasi-pulsed spot (MM9), lowest first: N<T<C<V<X<G or S.

The manual ranks ``G`` and ``S`` jointly as the most severe.
"""


@dataclass(frozen=True)
class DataFormat:
    """One ``FMT format`` value from Table 4-24 and its data element layout (Table 1-6).

    ``header_length`` counts the status, channel, and data type characters before the
    data digits of an ASCII element.
    """

    fmt: int
    encoding: DataEncoding
    terminator: Terminator
    status_field: StatusField
    data_digits: int | None
    header_length: int


DATA_FORMATS: dict[int, DataFormat] = {
    1: DataFormat(1, "ascii", "crlf_eoi", "letter", 12, 3),
    2: DataFormat(2, "ascii", "crlf_eoi", "none", 12, 0),
    3: DataFormat(3, "binary_4byte", "crlf_eoi", "binary", None, 0),
    4: DataFormat(4, "binary_4byte", "eoi", "binary", None, 0),
    5: DataFormat(5, "ascii", "comma", "letter", 12, 3),
    11: DataFormat(11, "ascii", "crlf_eoi", "letter", 13, 3),
    12: DataFormat(12, "ascii", "crlf_eoi", "none", 13, 0),
    13: DataFormat(13, "binary_8byte", "crlf_eoi", "binary", None, 0),
    14: DataFormat(14, "binary_8byte", "eoi", "binary", None, 0),
    15: DataFormat(15, "ascii", "comma", "letter", 13, 3),
    21: DataFormat(21, "ascii", "crlf_eoi", "eee", 13, 5),
    22: DataFormat(22, "ascii", "crlf_eoi", "none", 13, 0),
    25: DataFormat(25, "ascii", "comma", "eee", 13, 5),
}
"""Valid ``FMT`` formats.

Binary formats carry status in their own bit fields (Tables 1-13 and 1-15, PDF pages
66 and 74), which this module does not decode.
"""


def data_format(fmt: int) -> DataFormat:
    """Return the Table 4-24 layout for ``fmt`` or raise ``ValueError``."""
    try:
        return DATA_FORMATS[fmt]
    except KeyError:
        raise ValueError(f"FMT {fmt} is not defined in Table 4-24") from None


def parse_letter_status(
    code: str, *, source_data: bool = False
) -> MeasurementStatus | SourceDataStatus:
    """Classify a one-character status ``A`` from FMT 1, 5, 11, or 15 data.

    Args:
        code: The status character.
        source_data: True when the element is ``Source_data`` (Table 1-7).

    Raises:
        ValueError: If ``code`` is not defined for the element kind.
    """
    if source_data:
        return SourceDataStatus(code)
    return MeasurementStatus(code)


def decode_eee_status(code: str | int, module: ModuleKind) -> SmuStatus | CmuStatus:
    """Decode a three-digit summed status ``EEE`` from FMT 21 or 25 measurement data.

    Several conditions are reported as the sum of their values; for example, an
    A/D overflow while an SMU oscillates gives 3 (1 + 2).

    Raises:
        ValueError: If ``module`` is unknown, or ``code`` is not 0-255 or sets a bit
            that is not assigned for the module.
    """
    if module not in ("smu", "cmu"):
        raise ValueError(f"EEE status is defined for 'smu' or 'cmu', not {module!r}")
    value = int(code)
    flag_type: type[SmuStatus | CmuStatus] = SmuStatus if module == "smu" else CmuStatus
    assigned = 0
    for member in flag_type:
        assigned |= member.value
    if value < 0 or value & ~assigned:
        raise ValueError(f"EEE status {value} has bits not assigned for {module.upper()}")
    return flag_type(value)


@dataclass(frozen=True)
class MeasurementPoint:
    """One parsed measurement data element."""

    status: MeasurementStatus | SourceDataStatus | SmuStatus | CmuStatus
    channel: str
    quantity: str
    value: float
    raw: str


def parse_fmt1(raw: str) -> list[MeasurementPoint]:
    """Parse ``FMT 1`` output (ASCII, 12-digit data, ``ABC`` header).

    TODO: Implement strict parsing after confirming exact field widths from the manual.
    """
    _ = raw
    return []
