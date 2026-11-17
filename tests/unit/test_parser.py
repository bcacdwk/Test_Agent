"""Parser tests against Programming Guide Ed. 15 Tables 1-6 to 1-12 and 4-24, and the golden fixtures in
``tests/fixtures/flex/`` (FMT 1 and FMT 5)."""

import pytest

from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.parser import (
    CHANNEL_LETTERS,
    DATA_FORMATS,
    DATA_TYPES,
    INVALID_DATA_VALUE,
    CmuStatus,
    MeasurementStatus,
    SmuStatus,
    SourceDataStatus,
    data_format,
    decode_eee_status,
    parse_data,
    parse_element,
    parse_fmt1,
    parse_fmt5,
    parse_letter_status,
)
from tests.unit.flex_fixtures import FlexFixture, all_fixtures

DATA_FIXTURES = all_fixtures("fmt1", "fmt5")


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


# -- FMT 1 / FMT 5 data parsing ------------------------------------------------------------------------------------


def _parse(fixture: FlexFixture, text: str):
    return parse_fmt1(text) if fixture.kind == "fmt1" else parse_fmt5(text)


@pytest.mark.parametrize("fixture", DATA_FIXTURES, ids=lambda f: f.name)
def test_golden_fixture_parses_to_its_points(fixture: FlexFixture) -> None:
    for text in (fixture.body, fixture.wire):
        points = _parse(fixture, text)
        assert len(points) == len(fixture.points)
        for point, expected in zip(points, fixture.points, strict=True):
            assert point.status.value == expected.status
            assert (point.channel, point.data_type) == (expected.channel, expected.data_type)
            assert point.value == float(expected.data)
            assert point.raw == f"{expected.status}{expected.channel}{expected.data_type}{expected.data}"
            assert point.is_source == (expected.status in "WE")
    fmt = 1 if fixture.kind == "fmt1" else 5
    assert parse_data(fixture.wire, fmt) == _parse(fixture, fixture.wire)


def test_golden_fixtures_cover_every_letter_of_tables_1_7_and_1_10_to_1_12() -> None:
    points = [p for f in DATA_FIXTURES for p in f.points]
    assert {p.status for p in points} == set("NTCVXFGSUD") | set("WE")
    assert {p.channel for p in points} >= set("ABCDEFGHIJabcdefghij") | {"V", "Z"}
    assert {p.data_type for p in points} == set(DATA_TYPES)
    assert {f.kind for f in DATA_FIXTURES} == {"fmt1", "fmt5"}


def test_manual_staircase_example_layout() -> None:
    """PDF 199-201: per step Time, Data, Source_data; 11 steps; the source of the last step has status E."""
    fixture = next(f for f in DATA_FIXTURES if f.name == "fmt1_staircase_manual_example.txt")
    points = parse_fmt1(fixture.wire)
    assert len(points) == 33
    assert [p.data_type for p in points[:3]] == ["T", "I", "V"]
    assert [p.status for p in points if p.is_source] == [SourceDataStatus.FIRST_OR_INTERMEDIATE_STEP] * 10 + [
        SourceDataStatus.LAST_STEP
    ]
    assert points[1].value == pytest.approx(0.0001123e-3)
    assert points[-1].value == 3.0
    assert {p.channel_number for p in points} == {5}
    assert all(len(element) == 15 for element in fixture.body.split(","))


def test_point_properties() -> None:
    overflow = parse_element("VAI+199.999E+99")
    assert overflow.invalid and overflow.status is MeasurementStatus.OVER_RANGE_OR_SWEEP_ABORTED
    assert overflow.channel_number == 1
    assert parse_element("NbI+1.00000E-09").channel_number == 202
    assert parse_element("NjI+1.00000E-09").channel_number == 1002
    assert parse_element("NVI+1.00000E-03").channel_number is None  # GNDU
    assert parse_element("NZT+0.00000E+00").channel_number is None  # extraneous data
    assert not parse_element("CAI+1.00000E-03").invalid
    assert CHANNEL_LETTERS["J"] == 10


@pytest.mark.parametrize(
    "element",
    [
        "NAI+1.0000E-09",  # 11 data characters
        "NAI+1.000000E-09",  # 13 digits (FMT 11 width)
        "LAI+1.00000E-09",  # unknown status
        "NKI+1.00000E-09",  # channel K does not exist
        "NAA+1.00000E-09",  # unknown data type
        "NAI 1.00000E-09",  # missing sign
        "NAI+1.00000e-09",  # lower-case exponent
        "NAI+1.00000E-9 ",  # one-digit exponent
        "NAI+1.00000E+1A",
        "NAI+1234.567E+0",  # sign + 4 digits + '.' is not a listed form
        "",
    ],
)
def test_malformed_elements_are_rejected(element: str) -> None:
    with pytest.raises(FlexParseError):
        parse_element(element)


@pytest.mark.parametrize(
    "raw",
    [
        "NAI+1.00000E-09,",  # FMT 1 has no comma terminator
        "NAI+1.00000E-09,,NAI+2.00000E-09",
        "NAI+1.00000E-09;NAI+2.00000E-09",
        "garbage",
        "NAI+1.00000E-09\r\nNAI+2.00000E-09",
    ],
)
def test_malformed_fmt1_responses_are_rejected_with_raw_text(raw: str) -> None:
    with pytest.raises(FlexParseError) as info:
        parse_fmt1(raw)
    assert info.value.raw == raw


def test_fmt5_terminator_handling() -> None:
    assert parse_fmt5("NAI+1.00000E-09,") == parse_fmt5("NAI+1.00000E-09")
    assert parse_fmt5("NAI+1.00000E-09,\r\n") == parse_fmt1("NAI+1.00000E-09\r\n")
    with pytest.raises(FlexParseError):
        parse_fmt5("NAI+1.00000E-09,,")


def test_empty_response_has_no_points() -> None:
    assert parse_fmt1("") == []
    assert parse_fmt1("\r\n") == []
    assert parse_fmt5(",") == []


def test_parse_data_supports_fmt_1_and_5_only() -> None:
    with pytest.raises(ValueError, match="format 21"):
        parse_data("x", 21)
