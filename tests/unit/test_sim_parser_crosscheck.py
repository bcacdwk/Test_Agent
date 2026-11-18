"""Cross-check of the two independent FLEX implementations (blueprint 3, 9.2 WP1.6).

The simulator's formatter (``transport/sim/format.py``) and query handlers were written from the manual without
sharing code with ``driver/parser.py``, ``driver/discovery.py`` and ``driver/errors.py``; each side has its own golden
fixtures (``tests/fixtures/flex/format/*.yaml`` for the formatter, ``tests/fixtures/flex/*.txt`` for the parser).
Here each side is checked against the other side's output and fixtures:

1. formatter output (property test) and live simulator measurements (FMT 1/5, source data, time stamps, status
   letters) parse with the driver back to the same elements and values;
2. every simulator query answer parses with the driver's parsers (``*IDN?``, ``UNT?``, ``ERRX?``, ``*STB?``, serial
   poll, ``LOP?``, ``*TST?``, ``*CAL?``);
3. the formatter's fixtures parse with the driver parser;
4. the parser's fixtures are reproduced by the simulator (element headers, values, framing; exact wire text for
   ``ERRX?`` and ``UNT?``).

Known representational differences that are not disagreements (both are allowed by the manual): the simulator
writes the 12-digit value in engineering notation (exponent a multiple of 3), while some parser fixtures use other
``sn.nnnnnEsnn`` forms (PDF 51 lists all three digit layouts); the simulator's ``ERRX?`` message omits the
``; SLOTn`` suffix of the manual example (PDF 432).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from b1500_test_agent.driver.b1500 import B1500Driver, StaircaseSetup
from b1500_test_agent.driver.discovery import parse_auto_calibration, parse_idn, parse_lop, parse_unt
from b1500_test_agent.driver.errors import parse_errx, parse_self_test_result, parse_status_byte
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.driver.parser import INVALID_DATA_VALUE, parse_data
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.sim import ComplianceAt, ErrxFault, IdnOverride, InterlockOpen
from b1500_test_agent.transport.sim import SimTransport
from b1500_test_agent.transport.sim import format as simfmt
from tests.sim.helpers import load_scenario, noiseless, resistor_scenario
from tests.unit.flex_fixtures import FIXTURE_DIR, all_fixtures

FORMAT_FIXTURES = sorted((FIXTURE_DIR / "format").glob("*.yaml"))
R_OHM = 1000.0
_ENGINEERING = re.compile(r"[+-][1-9]\d{0,2}\.\d+E[+-]\d\d")
"""A normalized engineering-notation field (non-zero leading digit); the exponent check is done separately."""


def canonical(channel: int) -> int:
    """PG Table 4-1: channel 301 is channel 3."""
    return channel // 100 if channel > 10 and channel % 100 == 1 else channel


def on_the_wire(text: str) -> str:
    """What a transport hands to the driver: the message without the CR/LF read termination."""
    return text.removesuffix("\r\n")


# -- 1. simulator output -> driver parser ----------------------------------------------------------------------------

CHANNELS = [*range(1, 11), *(slot * 100 + sub for slot in range(1, 11) for sub in (1, 2))]
element_strategy = st.builds(
    simfmt.Element,
    status=st.sampled_from(sorted(simfmt.MEASUREMENT_STATUS | simfmt.SOURCE_STATUS)),
    channel=st.sampled_from(CHANNELS),
    dtype=st.sampled_from(sorted(simfmt.DATA_TYPES)),
    value=st.floats(min_value=-1e15, max_value=1e15, allow_nan=False, allow_infinity=False),
)


@settings(max_examples=300, deadline=None)
@given(elements=st.lists(element_strategy, min_size=1, max_size=40), fmt=st.sampled_from([1, 5]))
def test_formatter_output_parses_back(elements: list[simfmt.Element], fmt: int) -> None:
    points = parse_data(on_the_wire(simfmt.format_elements(elements, fmt)), fmt)
    assert len(points) == len(elements)
    for element, point in zip(elements, points, strict=True):
        assert point.status.value == element.status
        assert point.is_source == (element.status in simfmt.SOURCE_STATUS)
        assert point.channel_number == canonical(int(element.channel))
        assert point.data_type == element.dtype
        if element.status == "V":
            assert point.value == INVALID_DATA_VALUE and point.invalid
        else:
            assert point.value == pytest.approx(element.value, rel=5e-6, abs=1e-99)


def _resistor_sim() -> SimTransport:
    transport = SimTransport(resistor_scenario(R_OHM), state_file=None)
    transport.open()
    return transport


@pytest.mark.parametrize("tsc", [False, True])
@pytest.mark.parametrize("fmt", [1, 5])
def test_simulated_staircase_parses_with_the_driver(fmt: int, tsc: bool) -> None:
    transport = _resistor_sim()
    env = CompiledEnvelope(channels={1: ChannelEnvelope(role="a", max_abs_v=2.0, max_abs_i=0.01),
                                     3: ChannelEnvelope(role="b", max_abs_v=1.0, max_abs_i=0.01)})
    driver = B1500Driver(transport, OutputGuard(env))
    driver.set_format(fmt, 1)
    if tsc:
        transport.write("TSC 1")
    driver.enable([1, 3])
    driver.force_v(3, 0.0, icomp=0.01)
    setup = StaircaseSetup(channel=1, start=0.0, stop=1.0, points=6, icomp=0.01, measure=(1, 3))
    driver.staircase_v(setup)
    width = (4 if tsc else 2) + 1
    block = driver.execute_and_read(expected_points=setup.points * width, timeout_s=10.0)
    assert block.complete and transport.instrument.errors == []
    if fmt == 5:
        assert block.raw.endswith(",")
    for index, step in enumerate(block.steps(width)):
        volts = index * 0.2
        data = [p for p in step if p.data_type == "I"]
        times = [p for p in step if p.data_type == "T"]
        source = step[-1]
        assert [p.channel_number for p in data] == [1, 3]
        assert all(p.status.value == "N" for p in data)
        assert data[0].value == pytest.approx(volts / R_OHM, rel=1e-5, abs=1e-15)
        assert data[1].value == pytest.approx(-volts / R_OHM, rel=1e-5, abs=1e-15)
        assert source.is_source and source.channel_number == 1 and source.data_type == "V"
        assert source.status.value == ("E" if index == setup.points - 1 else "W")
        assert source.value == pytest.approx(volts, abs=1e-12)
        assert len(times) == (2 if tsc else 0)
        assert [step.index(t) for t in times] == ([0, 2] if tsc else [])


def test_simulated_compliance_and_abort_statuses_parse() -> None:
    transport = _resistor_sim()
    transport.inject(ComplianceAt(step=2, ch=3))
    env = CompiledEnvelope(channels={1: ChannelEnvelope(role="a", max_abs_v=2.0, max_abs_i=1e-3),
                                     3: ChannelEnvelope(role="b", max_abs_v=1.0, max_abs_i=1e-3)})
    driver = B1500Driver(transport, OutputGuard(env))
    driver.set_format(1, 0)
    driver.enable([1, 3])
    driver.force_v(3, 0.0, icomp=1e-3)  # 0.5 V / 1 kOhm stays below both compliances; only the fault limits
    driver.staircase_v(StaircaseSetup(channel=1, start=0.0, stop=0.5, points=5, icomp=1e-3, measure=(1, 3)))
    block = driver.execute_and_read(expected_points=10, timeout_s=10.0)
    statuses = ["".join(p.status.value for p in step) for step in block.steps(2)]
    assert statuses == ["NN", "NN", "TC", "VV", "VV"]  # T = other channel in compliance, then WM auto-abort dummies
    assert all(p.invalid for step in block.steps(2)[3:] for p in step)
    assert abs(block.steps(2)[2][1].value) == pytest.approx(1e-3)


# -- 2. simulator query answers -> driver parsers --------------------------------------------------------------------


def test_simulated_queries_parse_with_the_driver() -> None:
    scenario = noiseless(load_scenario("nmos_basic"))
    transport = SimTransport(scenario, state_file=None)
    transport.open()
    identity = parse_idn(transport.query("*IDN?"))
    assert identity.raw == scenario.idn and identity.model == "B1500A"
    inventory = parse_unt(transport.query("UNT?"))
    assert [(m.slot, m.model, m.revision) for m in inventory.modules] == [
        (s.slot, s.model, s.revision) for s in scenario.slots]
    assert parse_unt(transport.query("UNT? 1"), with_frame=True).modules == inventory.modules
    assert parse_errx(transport.query("ERRX?")) is None
    transport.inject(ErrxFault(after_cmd="BC", code=305))
    transport.write("BC")
    error = parse_errx(transport.query("ERRX?"))
    assert error is not None and (error.code, error.message) == (305, "Excess current in HPSMU.")
    transport.write("XX")  # unsupported -> error 100
    code_only = parse_errx(transport.query("ERRX? 1"))
    assert code_only is not None and code_only.code == 100 and code_only.message == ""
    status = parse_status_byte(transport.query("*STB?"))
    assert status.interlock_open  # nmos_basic: interlock open
    assert 0 <= transport.serial_poll() <= 255
    lop = parse_lop(transport.query("LOP?"))
    assert set(lop) == set(range(1, 11)) and not any(o.output_on for o in lop.values())
    transport.write("CN 5")  # SMU5 (MPSMU) of the lab layout
    transport.write("DV 5,0,0.5,1E-4")
    on = parse_lop(transport.query("LOP?"))
    assert on[5].output_on and on[5].state == "01" and not on[3].output_on
    transport.write("CL")
    assert parse_self_test_result(transport.query("*TST?")) == 0
    assert parse_self_test_result(transport.query("*CAL?")) == 0
    assert parse_auto_calibration(transport.query("*LRN? 31")) is False
    transport.write("CM 1")
    assert parse_auto_calibration(transport.query("*LRN? 31")) is True


# -- 3. formatter fixtures -> driver parser --------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [p for p in FORMAT_FIXTURES if _load(p)["kind"] == "data"], ids=lambda p: p.stem)
def test_formatter_fixtures_parse_with_the_driver(path: Path) -> None:
    fixture = _load(path)
    points = parse_data(on_the_wire(fixture["wire"]), fixture["fmt"])
    assert len(points) == len(fixture["elements"])
    for (status, channel, dtype, value), point in zip(fixture["elements"], points, strict=True):
        assert point.status.value == status and point.data_type == dtype
        assert point.channel_number == canonical(int(channel))
        expected = INVALID_DATA_VALUE if status == "V" else float(value)
        assert point.value == pytest.approx(expected, rel=1e-6, abs=1e-99)


def test_formatter_value_and_channel_fixtures_parse_with_the_driver() -> None:
    by_kind = {_load(p)["kind"]: _load(p) for p in FORMAT_FIXTURES}
    for value, field in by_kind["values"]["cases"]:
        (point,) = parse_data(f"NAI{field}", 1)
        assert point.value == float(field) and math.isclose(point.value, float(value), rel_tol=5e-6, abs_tol=1e-99)
    for channel, letter in by_kind["channels"]["cases"]:
        (point,) = parse_data(f"N{letter}I+0.00000E+00", 1)
        assert point.channel_number == canonical(int(channel))


# -- 4. parser fixtures -> simulator ---------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", all_fixtures("fmt1", "fmt5"), ids=lambda f: f.name)
def test_parser_fixtures_are_reproduced_by_the_formatter(fixture: Any) -> None:
    fmt = 1 if fixture.kind == "fmt1" else 5
    texts = []
    for point in fixture.points:
        element = simfmt.Element(point.status, point.channel, point.data_type, float(point.data))
        text = element.text()
        assert text[:3] == point.status + point.channel + point.data_type
        assert float(text[3:]) == pytest.approx(float(point.data), rel=1e-6, abs=1e-99)
        if _ENGINEERING.fullmatch(point.data) and int(point.data[-3:]) % 3 == 0:
            assert text[3:] == point.data  # same digit layout whenever the fixture uses engineering notation
        texts.append(point.status + point.channel + point.data_type + point.data)
    assert simfmt.frame(texts, fmt) == fixture.wire  # identical framing and terminator


def test_parser_query_fixtures_match_the_simulator() -> None:
    fixtures = {f.name: f for f in all_fixtures("idn", "unt", "errx", "lop", "stb", "tst")}
    scenario = noiseless(load_scenario("nmos_basic"))  # same seven modules as the UNT? fixture
    transport = SimTransport(scenario, state_file=None)
    transport.open()
    assert transport.query("UNT?") == fixtures["unt_example_station.txt"].body
    assert transport.query("ERRX?") == fixtures["errx_no_error.txt"].body
    transport.inject(IdnOverride(idn=fixtures["idn_manual_example.txt"].body))
    assert parse_idn(transport.query("*IDN?")).model_dump(exclude={"raw"}) == fixtures["idn_manual_example.txt"].expect
    shape = re.compile(r"LOP\s?\d{2}(,\d{2}){9}")
    assert shape.fullmatch(fixtures["lop_hpsmu_voltage_compliance.txt"].body)
    assert shape.fullmatch(transport.query("LOP?"))
    errx = re.compile(r'\d+,".*"')
    assert errx.fullmatch(fixtures["errx_excess_current.txt"].body)
    transport.inject(ErrxFault(after_cmd="BC", code=305))
    transport.write("BC")
    assert errx.fullmatch(transport.query("ERRX?"))
    transport.inject(InterlockOpen())
    assert parse_status_byte(transport.query("*STB?")).value & 8 == parse_status_byte(
        fixtures["stb_interlock_error.txt"].body).value & 8
    assert parse_self_test_result(fixtures["tst_slot3_and_mainframe_failed.txt"].body) == 1028
    lrn = all_fixtures("lrn")[0]
    transport.write("CM 1")
    transport.write("FMT 1,1")
    transport.write("MM 2,3,4")
    assert transport.query("*LRN? 31") == lrn.body  # the simulator answers in the fixture's form
    assert re.fullmatch(r"\d+", transport.query("*TST?"))


def test_probe_state_fixtures_match_the_simulator() -> None:
    """The simulator answers ``ERMOD?``, ``ERSSP?``, ``SPST?``, ``CORRST?`` and ``ADJ? ch,0`` in the fixtures' form
    (state seeded as the fixtures describe; the setting commands arrive with the family work packages)."""
    fixtures = {f.kind: f for f in all_fixtures("ermod", "erssp", "spst", "corrst", "adj")}
    transport = SimTransport(noiseless(load_scenario("lab_station")), state_file=None)
    transport.open()
    state = transport.instrument.state
    assert [transport.query(c) for c in ("ERMOD?", "ERSSP? 0", "SPST?", "CORRST? 7,3", "ADJ? 7,0")] == [
        "0", "0", "0", "0", fixtures["adj"].body]  # power-on state; ADJ? 3 = not performed
    state.selector_mode, state.selector_ports[0], state.spgu_output_active = 28, 3, True
    state.cmu_corrections[7] = {3: True}
    assert transport.query("ERMOD?") == fixtures["ermod"].body
    assert transport.query("ERSSP? 0") == fixtures["erssp"].body
    assert transport.query("SPST?") == fixtures["spst"].body
    assert transport.query("CORRST? 7,3") == fixtures["corrst"].body
