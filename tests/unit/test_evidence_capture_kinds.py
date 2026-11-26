"""The fixture kinds and record fields v2.1 adds to ``service/evidence.py`` (plan §4.6, WP21.6).

Every raw answer a bring-up stage settles has a fixture kind: the ASU/SCUU/phase-compensation ``*LRN?`` types
(``lrn62``, ``lrn63``, ``lrn81``, ``lrn90``), the MFCMU correction read-backs (``corrl``, ``dcorr``, ``corrdt``) and
the WGFMU instrument library's strings (``wgfmu_error``, ``wgfmu_warnings``; ``wgfmu_version`` from a probe record).
Each parses with the driver's own parser into ``expect``, a rejected answer keeps the parser's message, and the
capture's fixture text loads in the ``tests/fixtures/flex`` convention. The audit timings (``audit_facts``) become
record fields (``bringup._candidates``). The visa-loop capture of real ``H…`` runs is in
``tests/visa_loop/test_bringup_records.py``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from b1500_test_agent.bringup import FORMAT_PAGES, fixture_text
from b1500_test_agent.driver import flex
from b1500_test_agent.driver.cmu_data import parse_correction_data
from b1500_test_agent.models.audit import AuditEvent
from b1500_test_agent.models.validation import CapturedExchange, FixtureKind
from b1500_test_agent.service.evidence import (
    BUS_TIMING,
    READBACK_TIMING,
    audit_facts,
    parse_exchange,
    wgfmu_exchange,
)
from tests.unit.flex_fixtures import QUERY_KINDS, load_fixture

NEW_KINDS: tuple[FixtureKind, ...] = ("lrn62", "lrn63", "lrn81", "lrn90", "corrl", "dcorr", "corrdt", "wgfmu_error",
                                      "wgfmu_warnings", "wgfmu_version")


@pytest.mark.parametrize("command, response, kind, expect", [
    (flex.lrn_q(flex.LRN_ASU_PATH), "SAP3,0;SAP4,1", "lrn62", {"3": "smu", "4": "cmu"}),
    (flex.lrn_q(flex.LRN_ASU_PATH), "", "lrn62", {}),  # no ASU answers nothing (the parser's reading, L0 settles it)
    (flex.lrn_q(flex.LRN_ASU_1PA), "SAR3,0;SAR4,1", "lrn63", {"3": True, "4": False}),
    (flex.lrn_q(flex.LRN_SCUU_PATH), "SSP 7,3", "lrn81", {"7": 3}),
    (flex.lrn_q(flex.LRN_ADJ_MODE), "ADJ 7,1", "lrn90", {"7": 1}),
    (flex.corrl_q(7), "+3", "corrl", {"count": 3}),
    (flex.corrl_q(7, 2), "1.0E+05", "corrl", {"frequency_hz": 100000.0}),
    (flex.dcorr_q(7, "open"), "100,0.0,0.0", "dcorr", {"mode": 100, "primary": 0.0, "secondary": 0.0}),
])  # fmt: skip
def test_each_new_query_kind_parses_with_the_driver_parser(command: str, response: str, kind: str,
                                                           expect: object) -> None:
    exchange = parse_exchange(command, response + "\r\n")
    assert exchange is not None and exchange.problem is None, exchange
    assert (exchange.kind, exchange.command, exchange.response, exchange.expect) == (kind, command, response, expect)


def test_correction_data_keeps_every_value_and_settings_stay_lrn() -> None:
    answer = "1000000,1.0E-09,2.0E-06,0.1,0.2,0,0"
    exchange = parse_exchange(flex.corrdt_q(7, 1), answer)
    assert exchange is not None and exchange.kind == "corrdt"
    assert exchange.expect == dataclasses.asdict(parse_correction_data(answer))
    settings = parse_exchange(flex.lrn_q(flex.LRN_SETTINGS), "CM1;FMT1,0")
    assert settings is not None and settings.kind == "lrn"
    assert parse_exchange(flex.lrn_q(0), "CN1") is None  # a *LRN? type without a fixture kind


@pytest.mark.parametrize("command, response", [
    (flex.corrl_q(7), "three"), (flex.dcorr_q(7, "short"), "200,1,2"), (flex.lrn_q(flex.LRN_ASU_PATH), "SAP3,7"),
    (flex.lrn_q(flex.LRN_SCUU_PATH), "SSP 7,9"), (flex.corrdt_q(7, 1), "1,2,3"),
])  # fmt: skip
def test_an_answer_the_parser_rejects_keeps_its_message(command: str, response: str) -> None:
    exchange = parse_exchange(command, response)
    assert exchange is not None and exchange.problem and exchange.expect is None and exchange.response == response


def _event(**fields: object) -> AuditEvent:
    return AuditEvent(ts=datetime(2026, 11, 26, 8, 0, tzinfo=UTC), backend="visa", **fields)  # type: ignore[arg-type]


def test_the_library_strings_of_the_audit_become_wgfmu_fixtures() -> None:
    error = wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_update", data={"fn": "update", "rc": -6, "code": 3050},
                                  error="WgfmuError: update: firmware error 3050: Measurement data memory overflow"))
    assert error is not None and error.kind == "wgfmu_error" and error.command == "WGFMU_update"
    assert error.response == "firmware error 3050: Measurement data memory overflow"  # the library's own text
    assert error.expect == {"function": "update", "rc": -6, "code": 3050}
    library = wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_connect", data={"fn": "connect", "rc": -9},
                                    error="WgfmuError: connect: -9 WGFMU_LIBRARY_ERROR: Library error."))
    assert library is not None and library.expect == {"function": "connect", "rc": -9, "code": -9}
    summary = "2 warning(s): [normal] update: a vector was rounded | [severe] connect: channel 201 is not in Fast IV"
    warnings = wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_getWarningSummary", resp=summary,
                                     data={"fn": "warnings", "rc": 0}))
    assert warnings is not None and warnings.kind == "wgfmu_warnings" and warnings.response == summary
    assert warnings.expect == {"count": 2, "lines": ["[normal] update: a vector was rounded",
                                                     "[severe] connect: channel 201 is not in Fast IV"]}
    none = _event(ev="wgfmu_call", cmd="WGFMU_getWarningSummary", resp="0 warning(s)", data={"fn": "warnings"})
    assert wgfmu_exchange(none) is None
    odd = wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_getWarningSummary", resp="?", data={"fn": "warnings"}))
    assert odd is not None and odd.problem is not None
    assert wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_execute", data={"fn": "execute", "rc": 0})) is None
    assert wgfmu_exchange(_event(ev="query", cmd="*IDN?", resp="x")) is None


def test_every_new_kind_writes_a_fixture_the_flex_convention_loads(tmp_path: Path) -> None:
    assert set(NEW_KINDS) <= QUERY_KINDS and set(NEW_KINDS) <= set(FORMAT_PAGES)
    samples = {
        "lrn62": parse_exchange(flex.lrn_q(flex.LRN_ASU_PATH), "SAP3,0"),
        "lrn63": parse_exchange(flex.lrn_q(flex.LRN_ASU_1PA), "SAR3,1"),
        "lrn81": parse_exchange(flex.lrn_q(flex.LRN_SCUU_PATH), "SSP 7,0"),
        "lrn90": parse_exchange(flex.lrn_q(flex.LRN_ADJ_MODE), "ADJ 7,0"),
        "corrl": parse_exchange(flex.corrl_q(7), "0"),
        "dcorr": parse_exchange(flex.dcorr_q(7, "load"), "400,0.00001,49.8765"),
        "corrdt": parse_exchange(flex.corrdt_q(7, 1), "1000,0,0,0,0,0,0"),
        "wgfmu_error": wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_execute", error="WgfmuError: execute: x",
                                             data={"fn": "execute", "rc": -6, "code": 3001})),
        "wgfmu_warnings": wgfmu_exchange(_event(ev="wgfmu_call", cmd="WGFMU_getWarningSummary",
                                                resp="1 warning(s): [normal] update: y", data={"fn": "warnings"})),
        "wgfmu_version": CapturedExchange(kind="wgfmu_version", command="file version resource of wgfmu.dll",
                                          response="A.04.00.2440.5403",
                                          expect={"machine": "x64", "file_version": "A.04.00.2440.5403"}),
    }
    for kind, exchange in samples.items():
        assert exchange is not None and exchange.kind == kind and exchange.problem is None, (kind, exchange)
        path = tmp_path / f"{kind}_01.txt"
        path.write_text(fixture_text(exchange, "hardware capture of run H20261126T080000Z-0a0b", []), encoding="utf-8")
        fixture = load_fixture(path)
        assert (fixture.kind, fixture.command, fixture.body, fixture.expect) == (
            kind, exchange.command, exchange.response, exchange.expect)
        assert "PDF" in fixture.source and ("B1530A" in fixture.source) == kind.startswith("wgfmu")


def test_the_audit_timings_are_the_slowest_call_and_the_readback_per_value(tmp_path: Path) -> None:
    events = [
        _event(ev="bus_open", dur_ms=12.0), _event(ev="bus_lock", dur_ms=2.0), _event(ev="bus_close", dur_ms=30.0),
        _event(ev="query", cmd=flex.TST_Q, resp="0", dur_ms=95000.0),
        _event(ev="query", cmd=flex.adj_q(7, flex.ADJ_MEASURE), resp="0", dur_ms=31000.0),
        _event(ev="query", cmd=flex.adj_q(7, flex.ADJ_READ_LAST), resp="0", dur_ms=4.0),
        _event(ev="query", cmd=flex.corr_q(7, "open"), resp="0", dur_ms=900.0),
        _event(ev="wgfmu_call", cmd="WGFMU_doSelfCalibration", resp="0", dur_ms=50000.0, data={"fn": "x", "rc": 0}),
        _event(ev="wgfmu_call", cmd="WGFMU_dcmeasureValue", resp="1e-06", dur_ms=1.5, data={"fn": "x", "rc": 0}),
        _event(ev="wgfmu_call", cmd="WGFMU_getMeasureValues", resp="n=100000", dur_ms=2000.0, data={"fn": "x"}),
        _event(ev="wgfmu_call", cmd="WGFMU_getMeasureValues", resp="n=4000", dur_ms=80.0, data={"fn": "x"}),
        _event(ev="wgfmu_call", cmd="WGFMU_doSelfTest", dur_ms=9.0, error="WgfmuError: x", data={"fn": "x", "rc": -6}),
    ]
    (tmp_path / "audit.jsonl").write_text("".join(e.to_json_line() + "\n" for e in events), encoding="utf-8")
    exchanges, timings = audit_facts(tmp_path)
    assert timings == pytest.approx({BUS_TIMING: 0.030, "tst_s": 95.0, "adj_s": 31.0, "corr_s": 0.9,
                                     "wgfmu_self_cal_s": 50.0, "wgfmu_dc_read_s": 0.0015,
                                     READBACK_TIMING: 2.08 / 104000})  # a failed self-test call is no duration
    assert [e.kind for e in exchanges] == ["tst", "adj", "adj", "wgfmu_error"]
    assert audit_facts(tmp_path / "missing") == ([], {})
