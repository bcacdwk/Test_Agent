"""Status classification tests against Programming Guide Ed. 15 Tables 1-6 to 1-10, 4-24."""

import pytest

from b1500_test_agent.driver.parser import (
    DATA_FORMATS,
    INVALID_DATA_VALUE,
    CmuStatus,
    MeasurementStatus,
    SmuStatus,
    SourceDataStatus,
    data_format,
    decode_eee_status,
    parse_letter_status,
)


def test_letter_status_set_matches_table_1_10() -> None:
    assert {s.value for s in MeasurementStatus} == set("NTCVXFGSUD")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("V", MeasurementStatus.OVER_RANGE_OR_SWEEP_ABORTED),
        ("X", MeasurementStatus.OSCILLATION_OR_NOT_SETTLED),
        ("F", MeasurementStatus.FORCE_SATURATION),
        ("U", MeasurementStatus.CMU_NULL_LOOP_UNBALANCE),
        ("D", MeasurementStatus.CMU_IV_AMP_SATURATION),
    ],
)
def test_letter_status_meanings(code: str, expected: MeasurementStatus) -> None:
    assert parse_letter_status(code) is expected


@pytest.mark.parametrize("code", ["L", "W", "E", "Z", ""])
def test_letter_status_rejects_codes_not_in_table_1_10(code: str) -> None:
    with pytest.raises(ValueError):
        parse_letter_status(code)


def test_source_data_status_is_w_or_e() -> None:
    assert parse_letter_status("W", source_data=True) is SourceDataStatus.FIRST_OR_INTERMEDIATE_STEP
    assert parse_letter_status("E", source_data=True) is SourceDataStatus.LAST_STEP
    with pytest.raises(ValueError):
        parse_letter_status("N", source_data=True)


def test_eee_status_is_summed_per_module() -> None:
    smu = decode_eee_status("003", "smu")
    assert smu == SmuStatus.ADC_OVERFLOW | SmuStatus.OSCILLATION_OR_FORCE_SATURATION
    assert decode_eee_status("008", "smu") == SmuStatus.COMPLIANCE
    assert decode_eee_status(4, "cmu") == CmuStatus.IV_AMP_SATURATION
    assert decode_eee_status(2, "cmu") == CmuStatus.NULL_LOOP_UNBALANCE
    assert decode_eee_status("000", "smu") == SmuStatus.NORMAL


@pytest.mark.parametrize(
    ("code", "module"), [(8, "cmu"), (16, "cmu"), (32, "cmu"), (256, "smu"), (-1, "smu"), (1, "pgu")]
)
def test_eee_status_rejects_unassigned_bits(code: int, module: str) -> None:
    with pytest.raises(ValueError):
        decode_eee_status(code, module)  # type: ignore[arg-type]


def test_fmt_table_4_24() -> None:
    assert set(DATA_FORMATS) == {1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, 25}
    fmt5 = data_format(5)
    assert (fmt5.encoding, fmt5.terminator, fmt5.status_field, fmt5.data_digits) == (
        "ascii",
        "comma",
        "letter",
        12,
    )
    assert {f for f, d in DATA_FORMATS.items() if d.encoding == "binary_8byte"} == {13, 14}
    assert {f for f, d in DATA_FORMATS.items() if d.status_field == "eee"} == {21, 25}
    assert data_format(21).header_length == 5
    with pytest.raises(ValueError):
        data_format(6)


def test_invalid_data_sentinel() -> None:
    assert float("199.999E+99") == INVALID_DATA_VALUE
