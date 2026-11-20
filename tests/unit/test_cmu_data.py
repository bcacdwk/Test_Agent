"""MFCMU data parser (``driver/cmu_data.py``, WP8.1): impedance pairs per ``IMP`` model, monitor values, sampling
index, time stamps, source data and CMU status codes, against the golden blocks transcribed from the Programming
Guide's MFCMU examples (``tests/fixtures/flex/fmt1_cmu_*.txt``), plus the small ``CORR?``/``*LRN?`` answers."""

from __future__ import annotations

import json
import math

import pytest

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import (
    CMU_STATUS_SEVERITY,
    IMP_PARAMETERS,
    TABLE_IMP_MODES,
    CmuLayout,
    parse_adj_mode,
    parse_cmu_blocks,
    parse_corr_result,
    parse_lrn_channel_items,
    parse_scuu_path,
    worst_cmu_status,
)
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.parser import parse_data, parse_element
from tests.unit.flex_fixtures import FlexFixture, all_fixtures

CMU_FIXTURES = [f for f in all_fixtures("fmt1") if f.name.startswith("fmt1_cmu_")]


def layout_of(fixture: FlexFixture) -> CmuLayout:
    """The ``# cmu:`` header of a CMU golden block: the layout the manual's program set up."""
    line = next(line for line in fixture.path.read_text(encoding="utf-8").splitlines() if line.startswith("# cmu:"))
    return CmuLayout(**json.loads(line.split(":", 1)[1]))


def test_every_mfcmu_mode_has_a_golden_block() -> None:
    assert {layout_of(f).mode for f in CMU_FIXTURES} == {17, 18, 19, 20, 22, 23, 26}


@pytest.mark.parametrize("fixture", CMU_FIXTURES, ids=lambda f: f.name)
def test_golden_blocks_parse_into_readings(fixture: FlexFixture) -> None:
    layout = layout_of(fixture)
    points = parse_data(fixture.wire, 1)
    readings = parse_cmu_blocks(points, layout)
    assert len(readings) * layout.width == len(points)
    for reading in readings:
        assert (reading.primary.data_type, reading.secondary.data_type) == ("C", "Y")  # IMP 100: Cp-G
        assert reading.status == "N" and not reading.invalid
        assert (reading.osc is not None) == (layout.mode in (17, 18, 22, 23))  # LMN only in those modes
        assert (reading.source is not None) == (layout.mode in (18, 20, 22, 23))
        assert (reading.index is not None) == (layout.mode == 26)
        assert reading.time is not None and reading.time.data_type == "T"
    if readings[0].source is not None:
        assert [r.source.status.value for r in readings] == ["W"] * (len(readings) - 1) + ["E"]  # type: ignore[union-attr]


def test_manual_cv_sweep_values() -> None:
    """PG PDF 260: the first and last rows of the CV (DC bias) sweep result (Vg, Cp pF, G uS, OSC mV, DC V)."""
    fixture = next(f for f in CMU_FIXTURES if f.name == "fmt1_cmu_cv_sweep_manual_example.txt")
    readings = parse_cmu_blocks(parse_data(fixture.wire, 1), layout_of(fixture))
    assert len(readings) == 21
    first, last = readings[0], readings[-1]
    assert first.table_values() == {"Cp": (pytest.approx(4.96677e-12), "N"), "G": (pytest.approx(26.155e-6), "N")}
    assert (first.osc.value, first.dc.value, first.source.value) == (  # type: ignore[union-attr]
        pytest.approx(28.7732e-3), pytest.approx(-4.72468), -5.0)
    assert last.source.value == 5.0 and last.time.value == pytest.approx(0.8529)  # type: ignore[union-attr]
    assert {r.primary.channel_number for r in readings} == {10}


def test_manual_ct_sampling_index_comes_before_the_time() -> None:
    fixture = next(f for f in CMU_FIXTURES if f.name == "fmt1_cmu_ct_sampling_manual_example.txt")
    readings = parse_cmu_blocks(parse_data(fixture.wire, 1), layout_of(fixture))
    assert [r.index.value for r in readings] == list(range(1, 11))  # type: ignore[union-attr]
    assert readings[0].time.value == pytest.approx(0.10199)  # type: ignore[union-attr]
    assert readings[0].table_values()["Cp"][0] == pytest.approx(0.100051e-12)


def test_cf_sweep_source_is_the_frequency() -> None:
    fixture = next(f for f in CMU_FIXTURES if f.name == "fmt1_cmu_cf_sweep_manual_example.txt")
    readings = parse_cmu_blocks(parse_data(fixture.wire, 1), layout_of(fixture))
    assert [r.source.data_type for r in readings] == ["F"] * 10  # type: ignore[union-attr]
    assert readings[-1].source.value == 5e6  # type: ignore[union-attr]


def test_layout_widths_follow_pdf_46_to_49() -> None:
    assert CmuLayout(imp=100, mode=17).width == 2
    assert CmuLayout(imp=100, mode=17, monitor=True, timestamp=True).width == 5  # PDF 255: 5 elements
    assert CmuLayout(imp=100, mode=18, monitor=True, source=True, timestamp=True).width == 6  # PDF 259
    assert CmuLayout(imp=100, mode=20, monitor=True, source=True, timestamp=True).width == 4  # PDF 268
    assert CmuLayout(imp=100, mode=26, source=True, index=True, timestamp=True).width == 4  # PDF 283
    assert CmuLayout(imp=100, mode=19, monitor=True, source=True).width == 2  # neither monitor nor source in MM 19
    assert CmuLayout(imp=100, mode=17, index=True).width == 2  # the index exists only in C-t sampling
    assert CmuLayout(imp=100, mode=18, smu_channels=2, timestamp=True).width == 3 + 2 * 2
    with pytest.raises(ValueError):
        CmuLayout(imp=99, mode=17)
    with pytest.raises(ValueError):
        CmuLayout(imp=100, mode=2)
    with pytest.raises(ValueError):
        CmuLayout(imp=100, mode=17, smu_channels=1)


def test_mm18_with_an_smu_channel() -> None:
    raw = "NGT+1.00000E-03,NGC+100.000E-12,NGY+1.00000E-09,NCT+1.00000E-03,NCI+12.0000E-12,WGV-1.00000E+00"
    [reading] = parse_cmu_blocks(parse_data(raw, 1), CmuLayout(imp=100, mode=18, source=True, timestamp=True,
                                                               smu_channels=1))
    assert [p.channel_number for p in reading.smu] == [3] and reading.smu[0].value == 12e-12


def test_degrees_become_radians_in_the_table() -> None:
    """WP5.7 data contract: theta is stored in radian; IMP 11 answers degrees (Table 4-16, PDF 347)."""
    raw = "NGZ+1.59155E+03,NGP-89.0000E+00"
    [reading] = parse_cmu_blocks(parse_data(raw, 1), CmuLayout(imp=11, mode=17))
    assert reading.table_values() == {"Z": (1591.55, "N"), "theta": (pytest.approx(math.radians(-89.0)), "N")}
    [rad] = parse_cmu_blocks(parse_data("NGZ+1.59155E+03,NGR-1.55334E+00", 1), CmuLayout(imp=10, mode=17))
    assert rad.table_values()["theta"][0] == pytest.approx(-1.55334)


def test_table_modes_and_their_quantities() -> None:
    assert TABLE_IMP_MODES == {10, 11, 100, 101, 200, 201}
    names = {mode: tuple(p.table for p in IMP_PARAMETERS[mode]) for mode in TABLE_IMP_MODES}
    assert names == {10: ("Z", "theta"), 11: ("Z", "theta"), 100: ("Cp", "G"), 101: ("Cp", "D"),
                     200: ("Cs", "Rs"), 201: ("Cs", "D")}
    assert set(IMP_PARAMETERS) == set(flex.IMP_MODES)
    [reading] = parse_cmu_blocks(parse_data("NGZ+1.00000E+00,NGZ+2.00000E+00", 1), CmuLayout(imp=1, mode=17))
    with pytest.raises(ValueError, match="no run-table columns"):
        reading.table_values()


@pytest.mark.parametrize(("raw", "layout", "match"), [
    ("NGC+1.00000E-12", CmuLayout(imp=100, mode=17), "multiple"),  # half a pair
    ("NGY+1.00000E-12,NGC+1.00000E-12", CmuLayout(imp=100, mode=17), "data type"),  # swapped
    ("NGC+1.00000E-12,NHY+1.00000E-09", CmuLayout(imp=100, mode=17), "different channels"),
    ("NGC+1.00000E-12,NGY+1.00000E-09,NGV+1.00000E+00", CmuLayout(imp=100, mode=18, source=True), "status"),
    ("WGC+1.00000E-12,NGY+1.00000E-09", CmuLayout(imp=100, mode=17), "status"),
])
def test_malformed_blocks_are_rejected_with_their_text(raw: str, layout: CmuLayout, match: str) -> None:
    with pytest.raises(FlexParseError, match=match) as info:
        parse_cmu_blocks(parse_data(raw, 1), layout)
    assert info.value.raw


def test_cmu_status_codes() -> None:
    """Table 1-10 (PDF 53): U NULL loop unbalance, D IV amplifier saturation, V invalid (199.999E+99)."""
    assert CMU_STATUS_SEVERITY == "NUDXV"
    letters = [parse_element(f"{s}GC+1.00000E-12") for s in "NUDV"]
    assert worst_cmu_status(letters[:1]) == "N" and worst_cmu_status(letters[:3]) == "D"
    assert worst_cmu_status(letters) == "V" and worst_cmu_status([]) == "N"
    [reading] = parse_cmu_blocks(parse_data("UGC+1.00000E-12,VGY+199.999E+99", 1), CmuLayout(imp=100, mode=17))
    assert reading.status == "V" and reading.invalid
    assert reading.table_values()["Cp"] == (1e-12, "U")


def test_corr_result_and_learn_answers() -> None:
    assert [parse_corr_result(t) for t in ("0", "+1", "2\r\n")] == [0, 1, 2]
    for bad in ("3", "x", ""):
        with pytest.raises(FlexParseError):
            parse_corr_result(bad)
    assert parse_adj_mode("ADJ7,1", 7) == 1 and parse_adj_mode("ADJ 701,2", 7) == 2
    assert parse_adj_mode("ADJ 7,0;ADJ 9,1", 9) == 1
    with pytest.raises(FlexParseError):
        parse_adj_mode("ADJ 9,1", 7)
    with pytest.raises(FlexParseError):
        parse_adj_mode("ADJ 7,5", 7)
    assert parse_scuu_path("SSP7,4", 7) == 4 and parse_scuu_path("SSP 7,0", 7) is None
    assert parse_scuu_path("", 7) is None and parse_scuu_path("SSL7,1", 7) is None
    with pytest.raises(FlexParseError):
        parse_scuu_path("SSP7,9", 7)
    with pytest.raises(FlexParseError):
        parse_lrn_channel_items("SSP7,1;SSP7,2", "SSP")
    with pytest.raises(FlexParseError):
        parse_lrn_channel_items("SSP 7", "SSP")
