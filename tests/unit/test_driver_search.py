"""Search data and the guarded search operations (``driver/search.py``, ``driver/ops/search.py``; WP7.5).

- ``parse_search``/``parse_quasi_pulsed`` on the golden fixtures transcribed from the PG examples (Table 3-10 quasi-
  pulsed result ``CCV``, Table 3-11 linear search result) and a ``G`` result; wrong element counts, channels, data types
  and source data are refused.
- ``SearchSetup``/``QuasiPulseSetup`` command order (the PG example order), their model checks, and the guard: every
  source level is checked before anything is written; without a guard, nothing is written.
"""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.driver.b1500 import (
    B1500Driver,
    QuasiPulseSetup,
    SearchMonitor,
    SearchSetup,
    SearchSource,
    SyncSource,
)
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.driver.search import parse_quasi_pulsed, parse_search
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from tests.unit.flex_fixtures import FIXTURE_DIR, load_fixture


class Recorder:
    """A transport stand-in that records writes."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:  # pragma: no cover - not used
        raise AssertionError(cmd)


def points(name: str) -> Any:
    return parse_fmt1(load_fixture(FIXTURE_DIR / name).body)


def test_linear_search_result_of_the_manual_example() -> None:
    data = parse_search(points("fmt1_linear_search_manual_example.txt"), source_channel=4, source_quantity="V",
                        monitor_channel=5, monitor_quantity="I")
    assert data.found and not data.not_found and not data.stopped and data.status == "N"
    assert data.search.value == pytest.approx(1.4) and data.sense is not None
    assert data.sense.value == pytest.approx(1.03545e-3) and data.sense.channel == "E"


def test_binary_search_not_found_and_quasi_pulsed_compliance() -> None:
    data = parse_search(points("fmt1_binary_search_not_found.txt"), source_channel=401, source_quantity="V",
                        monitor_channel=3, monitor_quantity="I")
    assert data.not_found and data.status == "G" and data.search.value == pytest.approx(0.2)
    reading = parse_quasi_pulsed(points("fmt1_quasi_pulsed_manual_example.txt"), channel=3, quantity="V")
    assert str(reading.status.value) == "C" and reading.value == pytest.approx(7.759)


@pytest.mark.parametrize(("raw", "kwargs"), [
    ("NDV+1.40000E+00", {"monitor_channel": 5, "monitor_quantity": "I"}),  # Data_sense missing
    ("NDV+1.40000E+00,NEI+1.0E-03,NEI+1.0E-03", {"monitor_channel": 5, "monitor_quantity": "I"}),
    ("NCV+1.40000E+00,NEI+1.03545E-03", {"monitor_channel": 5, "monitor_quantity": "I"}),  # wrong search channel
    ("NDI+1.40000E+00,NEI+1.03545E-03", {"monitor_channel": 5, "monitor_quantity": "I"}),  # wrong quantity
    ("WDV+1.40000E+00,NEI+1.03545E-03", {"monitor_channel": 5, "monitor_quantity": "I"}),  # source data
    ("NDV+1.40000E+00,NEV+1.03545E-03", {"monitor_channel": 5, "monitor_quantity": "I"}),
])
def test_search_data_of_another_shape_is_refused(raw: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(FlexParseError):
        parse_search(parse_fmt1(raw), source_channel=4, source_quantity="V", **kwargs)


def test_quasi_pulsed_data_of_another_shape_is_refused() -> None:
    with pytest.raises(FlexParseError):
        parse_quasi_pulsed(parse_fmt1("CCV+7.75900E+00,CCV+7.75900E+00"), channel=3, quantity="V")
    with pytest.raises(FlexParseError):
        parse_quasi_pulsed(parse_fmt1("CCI+1.00000E-03"), channel=3, quantity="V")


BINARY = SearchSetup(mode=15, source=SearchSource(channel=4, start=0.0, stop=2.0, comp=1e-6),
                     monitor=SearchMonitor(channel=3, quantity="I", target=1e-7), limit=1e-9)
LINEAR = SearchSetup(mode=14, source=SearchSource(channel=4, start=0.0, stop=3.0, comp=0.01, range=12),
                     monitor=SearchMonitor(channel=5, quantity="I", target=1e-3, range=13), step=0.01,
                     sync=SyncSource(channel=5, polarity=1, offset=0.0, comp=0.01), post="last")
QUASI = QuasiPulseSetup(channel=3, stop=100.0, icomp=0.005)


def test_setup_commands_follow_the_manual_examples() -> None:
    assert LINEAR.commands() == ["MM 14", "LSM 2,3", "LSVM 1", "LSTM 0,0", "LGI 5,1,13,0.001",
                                 "LSV 4,12,0,3,0.01,0.01", "LSSV 5,1,0,0.01"]  # Table 3-11 (PG PDF 220)
    assert BINARY.commands() == ["MM 15", "BSM 1,2,1", "BSVM 1", "BST 0,0", "BGI 3,0,1E-09,0,1E-07",
                                 "BSV 4,0,0,2,1E-06"]
    assert QUASI.commands() == ["MM 9,3", "BDT 0,0", "BDM 0,0", "BDV 3,0,0,100,0.005"]  # Table 3-10 (PDF 217)
    assert LINEAR.points == 301 and BINARY.points == 19
    assert BINARY.model_copy(update={"limit": None, "repeats": 8}).points == 10
    negative = SearchSetup(mode=14, source=SearchSource(channel=3, start=0.0, stop=-20.0, comp=1e-3),
                           monitor=SearchMonitor(channel=3, quantity="I", target=-1e-6), step=-0.1)
    assert negative.linear_judge == "below" and "LGI 3,0,0,-1E-06" in negative.commands()


@pytest.mark.parametrize("make", [
    lambda: SearchSetup(mode=14, source=SearchSource(channel=4, start=0, stop=1, comp=1e-3),
                        monitor=SearchMonitor(channel=3, quantity="I", target=1e-6)),  # no step
    lambda: SearchSetup(mode=15, source=SearchSource(channel=4, start=0, stop=1, comp=1e-3),
                        monitor=SearchMonitor(channel=3, quantity="I", target=1e-6)),  # no limit/repeats
    lambda: SearchSetup(mode=15, source=SearchSource(channel=4, start=0, stop=1, comp=1e-3),
                        monitor=SearchMonitor(channel=3, quantity="I", target=1e-6), limit=1e-9, repeats=4),
    lambda: SearchSetup(mode=15, source=SearchSource(channel=4, start=0, stop=1, comp=1e-3),
                        monitor=SearchMonitor(channel=3, quantity="I", target=1e-6), limit=1e-9,
                        sync=SyncSource(channel=4, comp=1e-3)),  # sync on the source channel (error 278)
    lambda: SearchSource(channel=4, start=1, stop=1, comp=1e-3),  # error 276
    lambda: SearchSource(channel=4, start=0, stop=1, comp=0),
    lambda: SearchMonitor(channel=3, quantity="I", target=1e-6, range=7),
    lambda: QuasiPulseSetup(channel=3, stop=9.0, icomp=1e-3),  # |stop - start| >= 10 V
])
def test_setup_models_refuse_inconsistent_setups(make: Any) -> None:
    with pytest.raises(ValueError):
        make()


def envelope(**channels: ChannelEnvelope) -> CompiledEnvelope:
    return CompiledEnvelope(channels={int(k[2:]): v for k, v in channels.items()})


GATE = ChannelEnvelope(role="gate", max_abs_v=2.0, max_abs_i=1e-6, function="sweep_v", v_start=0.0, v_stop=2.0)
DRAIN = ChannelEnvelope(role="drain", max_abs_v=0.05, max_abs_i=1e-3, function="bias_v", v_start=0.05, v_stop=0.05)


def test_search_setup_writes_after_the_guard_checked_every_source() -> None:
    recorder = Recorder()
    driver = B1500Driver(recorder, OutputGuard(envelope(ch4=GATE, ch3=DRAIN)))  # type: ignore[arg-type]
    driver.search_setup(BINARY)
    assert recorder.writes == BINARY.commands()
    for setup, reason in [
        (BINARY.model_copy(update={"source": BINARY.source.model_copy(update={"stop": 2.5})}),
         "level_exceeds_envelope"),
        (BINARY.model_copy(update={"source": BINARY.source.model_copy(update={"comp": 1e-5})}),
         "compliance_exceeds_envelope"),
        (BINARY.model_copy(update={"sync": SyncSource(channel=3, polarity=1, offset=0.0, comp=1e-3)}),
         "level_exceeds_envelope"),  # the drain would follow the gate to 2 V
    ]:
        recorder.writes.clear()
        with pytest.raises(EnvelopeViolation) as info:
            driver.search_setup(setup)
        assert info.value.reason == reason and recorder.writes == []


def test_quasi_pulse_setup_is_guarded_and_needs_a_guard() -> None:
    recorder = Recorder()
    gate = GATE.model_copy(update={"max_abs_v": 100.0, "max_abs_i": 0.005, "v_stop": 100.0})
    driver = B1500Driver(recorder, OutputGuard(envelope(ch3=gate)))  # type: ignore[arg-type]
    driver.quasi_pulse_setup(QUASI)
    assert recorder.writes == QUASI.commands()
    recorder.writes.clear()
    with pytest.raises(EnvelopeViolation):
        driver.quasi_pulse_setup(QUASI.model_copy(update={"measure_channel": 4}))  # not in the plan
    with pytest.raises(EnvelopeViolation) as info:
        B1500Driver(recorder).quasi_pulse_setup(QUASI)  # type: ignore[arg-type]
    assert info.value.reason == "no_guard" and recorder.writes == []
    with pytest.raises(EnvelopeViolation):
        B1500Driver(recorder).search_setup(BINARY)  # type: ignore[arg-type]
    assert recorder.writes == []
