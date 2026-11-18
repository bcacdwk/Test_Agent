"""Query-response parsers: *IDN?, UNT?, LOP?, ERRX?, *STB?, *TST?/*CAL? against the golden fixtures and the manual."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver.discovery import all_outputs_off, parse_idn, parse_lop, parse_unt
from b1500_test_agent.driver.errors import (
    FlexParseError,
    failed_units,
    parse_errx,
    parse_self_test_result,
    parse_status_byte,
    status_flags,
)
from b1500_test_agent.models.station import StatusByte
from tests.unit.flex_fixtures import FIXTURE_DIR, FlexFixture, all_fixtures, load_fixture

QUERY_FIXTURES = all_fixtures("idn", "unt", "errx", "lop", "stb", "tst")


def test_fixture_convention_holds_for_every_file() -> None:
    names = sorted(p.name for p in FIXTURE_DIR.glob("*.txt"))
    assert names and [f.name for f in all_fixtures()] == names
    for fixture in all_fixtures():
        assert "PDF " in fixture.source and fixture.command
    assert {f.kind for f in QUERY_FIXTURES} == {"idn", "unt", "errx", "lop", "stb", "tst"}


def test_fixture_loader_rejects_a_file_without_a_page_citation(tmp_path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("# source: somewhere\n# kind: stb\n# command: *STB?\n# expect: 0\n0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PDF"):
        load_fixture(bad)


@pytest.mark.parametrize("fixture", QUERY_FIXTURES, ids=lambda f: f.name)
def test_query_fixture(fixture: FlexFixture) -> None:
    text = fixture.body + "\r\n"  # the transport may or may not strip the terminator
    expect = fixture.expect
    if fixture.kind == "idn":
        identity = parse_idn(text)
        assert identity.model_dump(exclude={"raw"}) == expect
        assert identity.raw == fixture.body
    elif fixture.kind == "unt":
        inventory = parse_unt(text)
        assert {str(m.slot): m.model for m in inventory.modules} == expect
    elif fixture.kind == "errx":
        error = parse_errx(text)
        assert (None if error is None else error.model_dump()) == expect
    elif fixture.kind == "lop":
        outputs = parse_lop(text)
        assert {str(slot): out.state for slot, out in outputs.items()} == expect
        assert {slot for slot, out in outputs.items() if out.output_on} == {
            int(slot) for slot, code in expect.items() if code != "00"
        }
    elif fixture.kind == "stb":
        status = parse_status_byte(text)
        assert status.value == expect["value"] and status_flags(status) == expect["flags"]
    elif fixture.kind == "tst":
        result = parse_self_test_result(text)
        assert result == expect["value"] and failed_units(result) == expect["failed"]
    else:  # pragma: no cover - the loader rejects unknown kinds
        raise AssertionError(fixture.kind)


def test_idn_rejects_malformed_answers() -> None:
    for text in ("Agilent Technologies,B1500A,0", "", "a,,0,x", "a,b,c,d,e"):
        with pytest.raises(FlexParseError):
            parse_idn(text)


def test_unt_with_frame_and_malformed_answers() -> None:
    slots = ";".join(["B1517A,0"] + ["0,0"] * 9)
    assert [m.model for m in parse_unt("B1500A,0;" + slots, with_frame=True).modules] == ["B1517A"]
    for text in (slots + ";0,0", "B1517A;" + ";".join(["0,0"] * 9), ";".join(["0,0"] * 9), ""):
        with pytest.raises(FlexParseError):
            parse_unt(text)


def test_lop_accepts_a_space_after_the_header_and_fails_safe_on_unknown_codes() -> None:
    outputs = parse_lop("LOP 00,00,00,00,00,00,00,00,00,99")
    assert outputs[10].output_on and outputs[10].state == "99"
    assert all_outputs_off(parse_lop("LOP00,00,00,00,00,00,00,00,00,00"))
    assert not all_outputs_off(outputs)
    assert not all_outputs_off({})
    for text in ("LOP00,00", "00,00,00,00,00,00,00,00,00,00", "LOP0,00,00,00,00,00,00,00,00,00", "LOP?"):
        with pytest.raises(FlexParseError):
            parse_lop(text)


def test_errx_forms() -> None:
    assert parse_errx("0") is None
    assert parse_errx('0,"No Error."\r\n') is None
    error = parse_errx("305")  # ERRX? 1 returns the code only
    assert error is not None and (error.code, error.message) == (305, "")
    error = parse_errx('121,"Wrong command, message with commas."')
    assert error is not None and error.message == "Wrong command, message with commas."
    with pytest.raises(FlexParseError):
        parse_errx('"No Error."')


@pytest.mark.parametrize("text", ['0,"No Error."', '+0,"No Error."', "0,", "+0,", "0", "+0", ' +0 , "No Error." \r'])
def test_errx_every_success_form_is_success(text: str) -> None:
    """Blueprint v2 1.1 lab pitfall: the PG prints ``0,"No Error."``, the lab firmware answers ``+0,...``."""
    assert parse_errx(text) is None


def test_errx_signed_error_codes_keep_code_and_message() -> None:
    error = parse_errx('+305,"Excess current in HPSMU.; SLOT1"')
    assert error is not None and (error.code, error.message) == (305, "Excess current in HPSMU.; SLOT1")
    error = parse_errx("+121")
    assert error is not None and error.code == 121
    for bad in ("+", ",0", "No Error", "0x10,"):
        with pytest.raises(FlexParseError):
            parse_errx(bad)


def test_integer_answers_accept_an_explicit_plus_sign() -> None:
    assert parse_status_byte("+40").value == 40 and parse_status_byte(" 40\r\n").value == 40
    assert parse_self_test_result("+0") == 0 and parse_self_test_result("+1028") == 1028
    for bad in ("-1", "+", "256", "+256", "4 0", "0x28"):
        with pytest.raises(FlexParseError):
            parse_status_byte(bad)
    for bad in ("-0", "+2048", "ok"):
        with pytest.raises(FlexParseError):
            parse_self_test_result(bad)


def test_status_byte_bits() -> None:
    assert status_flags(StatusByte(value=0)) == []
    assert status_flags(1 + 2 + 16 + 64) == ["data_ready", "wait", "set_ready", "rqs"]
    assert StatusByte(value=8).interlock_open
    for text in ("256", "-1", "x", ""):
        with pytest.raises(FlexParseError):
            parse_status_byte(text)


def test_self_test_results() -> None:
    assert failed_units(0) == []
    assert failed_units(2047) == [f"slot {n}" for n in range(1, 11)] + ["mainframe"]
    with pytest.raises(ValueError):
        failed_units(2048)
    with pytest.raises(FlexParseError):
        parse_self_test_result("2048")
