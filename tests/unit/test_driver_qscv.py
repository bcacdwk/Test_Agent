"""Quasi-static C-V data and the guarded QSCV operations (``driver/qscv.py``, ``driver/ops/qscv.py``; WP8.5).

- ``QscvSource``/``QscvSetup``: the step count (``|stop - start| / step - 1``), the measured step voltages (start and
  stop excluded, back again for a double sweep), the joined-transition case (step = cvoltage), the nominal duration and
  the command order of the PG example (Table 3-17, PDF 243); inconsistent setups are refused.
- The guard: the source at start and stop against its compliance and the measurement channel before anything is
  written; without a guard nothing is written.
- ``parse_qscv``/``parse_qscv_offset``: ``[DataL,] DataC, Source_data`` per step (PG p49) and the one offset datum;
  other shapes, channels and data types are refused.
"""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver, QscvSetup, QscvSource
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.parser import parse_fmt1
from b1500_test_agent.driver.qscv import parse_qscv, parse_qscv_offset
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope


class Recorder:
    """A transport stand-in that records writes."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str, *, timeout_s: float | None = None) -> str:  # pragma: no cover - not used
        raise AssertionError(cmd)


SOURCE = QscvSource(channel=6, start=2.0, stop=-2.5, step=0.05, icomp=1e-6)
SETUP = QscvSetup(source=SOURCE, measure_channel=None, hold=5.0, range_code=-12)
EXAMPLE = QscvSetup(source=QscvSource(channel=2, start=3.2, stop=-7.2, step=0.2, cvoltage=0.25 * 0.8, icomp=0.1),
                    hold=5.0, range_code=-10)


def test_steps_and_step_voltages() -> None:
    assert SOURCE.steps == 89 and SOURCE.direction == -1.0 and SOURCE.contiguous
    volts = SOURCE.step_voltages()
    assert len(volts) == 89 and volts[0] == pytest.approx(1.95) and volts[-1] == pytest.approx(-2.45)
    double = SOURCE.model_copy(update={"double": True})
    assert len(double.step_voltages()) == 178 and double.step_voltages()[89] == pytest.approx(-2.45)
    assert EXAMPLE.source.steps == 51 and EXAMPLE.points == 51  # PG Table 3-17: 3.2 -> -7.2 V, 0.2 V steps


def test_command_order_follows_the_manual_example() -> None:
    assert EXAMPLE.commands() == ["MM 13,2", "QSC 0", "QSO 0", "QSL 1,1", "QSM 2,1", "QSR -10", "QST 0.1,0.1,5,0,0",
                                  "QSV 2,1,0,3.2,-7.2,0.2,51,0.1", "QSZ 0"]
    compatible = EXAMPLE.model_copy(update={"operation": "compatible", "offset": "cancel", "measure_channel": 3,
                                            "leakage_data": False, "compensation": False})
    assert compatible.commands()[:3] == ["MM 13,3", "QSC 1", "QSL 0,0"]  # QSO needs QSC 0: not sent
    assert compatible.commands()[-1] == "QSZ 1" and compatible.measured_channel == 3
    assert QscvSetup(source=SOURCE, offset="measure").commands()[-1] == "QSZ 0"  # QSZ 2 is the measurement itself


def test_duration_and_elements() -> None:
    # joined transitions: the first step integrates the leakage twice, every later one once (PG p116)
    assert SETUP.duration_s() == pytest.approx(5.0 + 0.3 + 88 * 0.2)
    apart = SETUP.model_copy(update={"source": SOURCE.model_copy(update={"cvoltage": 0.025}), "delay2": 0.1})
    assert not apart.source.contiguous
    assert apart.duration_s() == pytest.approx(5.0 + 89 * (0.1 + 0.1 + 0.1 + 0.1))
    assert SETUP.elements_per_step == 3 and SETUP.model_copy(update={"leakage_data": False}).elements_per_step == 2
    assert SETUP.range_a == 1e-8 and SETUP.offset_duration_s() == pytest.approx(0.3)


@pytest.mark.parametrize("make", [
    lambda: QscvSource(channel=6, start=1.0, stop=1.0, step=0.05, icomp=1e-6),
    lambda: QscvSource(channel=6, start=0.0, stop=1.0, step=0.3, icomp=1e-6),  # not a whole number of steps
    lambda: QscvSource(channel=6, start=0.0, stop=0.05, step=0.05, icomp=1e-6),  # 0 measured steps
    lambda: QscvSource(channel=6, start=0.0, stop=1.0, step=0.05, cvoltage=0.1, icomp=1e-6),  # cvoltage > step
    lambda: QscvSource(channel=6, start=0.0, stop=1.0, step=0.05, icomp=0.0),
    lambda: QscvSource(channel=6, start=0.0, stop=1.0, step=0.05, icomp=1e-6, range=3),
    lambda: QscvSetup(source=SOURCE, range_code=-8),
])
def test_inconsistent_setups_are_refused(make: Any) -> None:
    with pytest.raises(ValueError):
        make()


def envelope(**channels: ChannelEnvelope) -> CompiledEnvelope:
    return CompiledEnvelope(channels={int(k[2:]): v for k, v in channels.items()})


GATE = ChannelEnvelope(role="gate", max_abs_v=2.5, max_abs_i=1e-6, function="sweep_v", v_start=2.0, v_stop=-2.5)
BULK = ChannelEnvelope(role="bulk", max_abs_v=0.0, max_abs_i=1e-6, function="ground", v_start=0.0, v_stop=0.0)


def test_setup_writes_after_the_guard_checked_the_source() -> None:
    recorder = Recorder()
    driver = B1500Driver(recorder, OutputGuard(envelope(ch6=GATE, ch5=BULK)))  # type: ignore[arg-type]
    driver.qscv_setup(SETUP)
    assert recorder.writes == SETUP.commands()
    for setup, reason in [
        (SETUP.model_copy(update={"source": SOURCE.model_copy(update={"start": 2.9, "stop": -2.5})}),
         "level_exceeds_envelope"),
        (SETUP.model_copy(update={"source": SOURCE.model_copy(update={"icomp": 1e-5})}), "compliance_exceeds_envelope"),
    ]:
        recorder.writes.clear()
        with pytest.raises(EnvelopeViolation) as info:
            driver.qscv_setup(setup)
        assert info.value.reason == reason and recorder.writes == []
    with pytest.raises(EnvelopeViolation):
        driver.qscv_setup(SETUP.model_copy(update={"measure_channel": 4}))  # not in the plan
    assert recorder.writes == []
    with pytest.raises(EnvelopeViolation) as info:
        B1500Driver(recorder).qscv_setup(SETUP)  # type: ignore[arg-type]
    assert info.value.reason == "no_guard" and recorder.writes == []


def test_parse_qscv_blocks() -> None:
    raw = "NFI+1.95002E-09,NFC+42.4417E-12,WFV+1.95000E+00,NFI+1.89867E-09,NFC+67.1633E-12,EFV+1.90000E+00"
    steps = parse_qscv(parse_fmt1(raw), channel=6, source_channel=6, leakage=True, steps=2)
    assert [s.status for s in steps] == ["N", "N"] and steps[1].capacitance.value == pytest.approx(67.1633e-12)
    assert steps[0].leakage is not None and steps[0].leakage.value == pytest.approx(1.95002e-9)
    assert steps[1].source.value == pytest.approx(1.9)
    plain = parse_qscv(parse_fmt1("NFC+42.4417E-12,EFV+1.95000E+00"), channel=6, source_channel=6, leakage=False,
                       steps=1)
    assert plain[0].leakage is None


@pytest.mark.parametrize(("raw", "kwargs"), [
    ("NFC+42.4417E-12,WFV+1.95000E+00", {"leakage": True, "steps": 1}),  # DataL missing
    ("NFI+1.9E-09,NFC+42.4E-12,WFV+1.95E+00", {"leakage": True, "steps": 2}),  # one block short
    ("NEI+1.9E-09,NEC+42.4E-12,WFV+1.95E+00", {"leakage": True, "steps": 1}),  # data of another channel
    ("NFI+1.9E-09,NFV+42.4E-12,WFV+1.95E+00", {"leakage": True, "steps": 1}),  # C datum with type V
    ("NFI+1.9E-09,NFC+42.4E-12,NFV+1.95E+00", {"leakage": True, "steps": 1}),  # no source status W/E
])
def test_qscv_data_of_another_shape_is_refused(raw: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(FlexParseError):
        parse_qscv(parse_fmt1(raw), channel=6, source_channel=6, **kwargs)


def test_offset_datum() -> None:
    assert parse_qscv_offset(parse_fmt1("NFC+2.50000E-13"), channel=6).value == pytest.approx(2.5e-13)
    for raw in ("NFC+2.5E-13,NFC+2.5E-13", "NFI+2.5E-13", "NEC+2.5E-13"):
        with pytest.raises(FlexParseError):
            parse_qscv_offset(parse_fmt1(raw), channel=6)
