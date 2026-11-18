"""B1500Driver over a spy transport: command sequences, the XE/read protocol, error draining and state tracking."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.b1500 import B1500Driver, RawBlock, StaircaseSetup
from b1500_test_agent.driver.errors import DriverError, DriverStateError, FlexParseError
from b1500_test_agent.driver.guard import OutputGuard
from b1500_test_agent.models.measurement import Integration, SweepTiming
from b1500_test_agent.models.station import InstrumentError
from tests.unit.driver_helpers import ReadTimeout, SpyTransport, envelope
from tests.unit.flex_fixtures import all_fixtures

ENV = envelope(ch1=(3.0, 1e-6), ch3=(0.1, 1e-3))
STAIRCASE = next(f for f in all_fixtures("fmt1") if f.name == "fmt1_staircase_two_channels_compliance.txt")


def _driver(**spy_kwargs: object) -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport(**spy_kwargs)  # type: ignore[arg-type]
    return B1500Driver(spy, OutputGuard(ENV)), spy


# -- A: queries ---------------------------------------------------------------------------------------------------


def test_identify_and_modules() -> None:
    driver, spy = _driver(
        answers={
            "*IDN?": "Agilent Technologies,B1500A,0,A.04.03.2010.0130\r\n",
            "UNT?": "B1511B,0;0,0;B1517A,0;0,0;0,0;0,0;0,0;0,0;0,0;0,0",
        }
    )
    assert driver.identify().model == "B1500A"
    assert [(m.slot, m.model) for m in driver.modules().modules] == [(1, "B1511B"), (3, "B1517A")]
    assert spy.sent == ["*IDN?", "UNT?"]


def test_errors_drain_until_code_zero() -> None:
    driver, spy = _driver(answers={"ERRX?": ['305,"Excess current in HPSMU.; SLOT1"', '100,"Undefined GPIB command."',
                                             '0,"No Error."']})  # fmt: skip
    assert driver.errors() == [
        InstrumentError(code=305, message="Excess current in HPSMU.; SLOT1"),
        InstrumentError(code=100, message="Undefined GPIB command."),
    ]
    assert spy.sent == ["ERRX?"] * 3


def test_errors_without_drain_reads_one_entry() -> None:
    driver, spy = _driver(answers={"ERRX?": ['202,"Interlock circuit must be closed."', '0,"No Error."']})
    assert [e.code for e in driver.errors(drain=False)] == [202]
    assert driver.errors(drain=False) == []
    assert spy.sent == ["ERRX?", "ERRX?"]


def test_errors_that_never_drain_raise() -> None:
    driver, _ = _driver(answers={"ERRX?": '305,"Excess current."'})
    with pytest.raises(DriverError, match="did not drain"):
        driver.errors()


def test_status_byte_query_and_serial_poll() -> None:
    driver, spy = _driver(answers={"*STB?": "40"}, stb=8)
    assert driver.status_byte().interlock_open
    assert driver.status_byte(poll=True).value == 8
    assert spy.sent == ["*STB?"]
    assert ("poll", "") in spy.log


def test_output_state_via_lop() -> None:
    driver, _ = _driver(answers={"LOP?": "LOP01,00,11,00,00,00,00,00,00,00"})
    outputs = driver.output_state()
    assert {slot for slot, out in outputs.items() if out.output_on} == {1, 3}
    assert outputs[3].state == "11"


def test_wait_complete() -> None:
    driver, spy = _driver(answers={"*OPC?": ["1", "0"]})
    driver.wait_complete(timeout_s=5)
    assert spy.timeouts[-1] == 5
    with pytest.raises(FlexParseError):
        driver.wait_complete()


# -- B: state -----------------------------------------------------------------------------------------------------


def test_self_test_and_calibration_results() -> None:
    driver, spy = _driver(answers={"*TST?": "0", "*CAL?": "1028"})
    assert driver.self_test(timeout_s=600) == 0
    assert driver.self_calibrate(timeout_s=600) == 1028
    assert spy.sent == ["*TST?", "*CAL?"]
    assert spy.timeouts == [600, 600]


def test_reset_is_sent_alone_and_restores_the_default_format() -> None:
    driver, spy = _driver()
    driver.set_format(5, 1)
    driver.reset()
    assert spy.sent == ["FMT 5,1", "*RST"]
    assert driver.data_format == (1, 0)


def test_zero_and_disconnect_with_channels() -> None:
    driver, spy = _driver()
    driver.zero([1, 3])
    driver.disconnect([3, 1])
    assert spy.sent == ["DZ 1,3", "CL 3,1"]


# -- C: measurement -------------------------------------------------------------------------------------------------


def test_measurement_setup_sequence() -> None:
    driver, spy = _driver()
    driver.set_format()
    driver.set_integration(1, 2, 1, chs=[1, 3])
    driver.apply_integration(Integration(adc="high_speed", mode="manual", n=4), [3])
    driver.set_range(3, "I", -18)
    driver.set_range(1, "V", 0)
    assert spy.sent == ["FMT 1,1", "AAD 1,1", "AAD 3,1", "AIT 1,2,1", "AAD 3,0", "AIT 0,1,4", "RI 3,-18", "RV 1,0"]
    with pytest.raises(ValueError):
        driver.set_range(1, "X", 0)  # type: ignore[arg-type]


def test_staircase_setup_sends_mm_cmm_wv_wt_wm_in_order() -> None:
    driver, spy = _driver()
    setup = StaircaseSetup(
        channel=1,
        start=0.0,
        stop=3.0,
        points=31,
        icomp=1e-6,
        vrange=200,
        double=True,
        measure=(3, 1),
        operation={3: 1, 1: 1},
        timing=SweepTiming(hold_s=0.1, delay_s=0.01),
        auto_abort=False,
        post="stop",
    )
    driver.staircase_v(setup)
    assert spy.sent == ["MM 2,3,1", "CMM 3,1", "CMM 1,1", "WV 1,3,200,0,3,31,1E-06", "WT 0.1,0.01", "WM 1,2"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"icomp": 0.0},
        {"vrange": -20},
        {"measure": (3, 3)},
        {"measure": ()},
        {"operation": {1: 1}},  # channel 1 is not measured
        {"operation": {3: 5}},
        {"sweep": "log", "start": 0.0},
        {"sweep": "log", "start": -1.0},
        {"points": 0},
        {"channel": 11},
    ],
)
def test_staircase_setup_validation(overrides: dict) -> None:
    values = {"channel": 1, "start": 0.1, "stop": 3.0, "points": 11, "icomp": 1e-6, "measure": (3,)} | overrides
    with pytest.raises(ValidationError):
        StaircaseSetup.model_validate(values)


def test_execute_and_read_parses_the_current_format() -> None:
    driver, spy = _driver(reads=[STAIRCASE.wire])
    driver.set_format(1, 1)
    block = driver.execute_and_read(expected_points=9, timeout_s=12.5)
    assert isinstance(block, RawBlock)
    assert spy.sent == ["FMT 1,1", "XE"]
    assert spy.timeouts == [12.5]
    assert block.raw == STAIRCASE.wire and block.fmt == 1 and block.complete
    assert block.read_at >= block.xe_at and block.duration_s >= 0
    steps = block.steps(3)
    assert len(steps) == 3 and steps[-1][2].is_source
    assert not driver.measurement_pending
    with pytest.raises(ValueError):
        block.steps(4)


def test_short_block_is_incomplete_not_an_error() -> None:
    driver, _ = _driver(reads=["NAI+1.00000E-12,NCI+5.00000E-09"])
    block = driver.execute_and_read(expected_points=9, timeout_s=1)
    assert not block.complete and len(block.points) == 2


def test_fmt5_block() -> None:
    driver, _ = _driver(reads=["NCI+1.00000E-06,WAV+0.00000E+00,"])
    driver.set_format(5, 1)
    block = driver.execute_and_read(expected_points=2, timeout_s=1)
    assert block.complete and block.fmt == 5


def test_garbage_raises_parse_error_with_raw_text() -> None:
    driver, _ = _driver(reads=["NAI+1.00000E-12,#garbage#"])
    with pytest.raises(FlexParseError) as info:
        driver.execute_and_read(expected_points=2, timeout_s=1)
    assert info.value.raw == "NAI+1.00000E-12,#garbage#"
    assert not driver.measurement_pending


def test_read_failure_leaves_the_measurement_pending_and_blocks_everything_but_abort() -> None:
    driver, spy = _driver(reads=[ReadTimeout("no data")], answers={"ERRX?": '0,"No Error."'})
    with pytest.raises(ReadTimeout):
        driver.execute_and_read(expected_points=3, timeout_s=1)
    assert driver.measurement_pending
    for refused in (
        lambda: driver.force_v(3, 0.05, icomp=1e-3),
        lambda: driver.set_format(),
        lambda: driver.errors(),
        lambda: driver.reset(),
        lambda: driver.execute_and_read(expected_points=1, timeout_s=1),
    ):
        with pytest.raises(DriverStateError):
            refused()
    assert spy.sent == ["XE"]
    driver.abort()
    assert not driver.measurement_pending
    assert driver.errors() == []
    assert spy.sent == ["XE", "AB", "ERRX?"]


def test_cleanup_while_pending_sends_ab_alone_first() -> None:
    driver, spy = _driver(reads=[ReadTimeout("no data")])
    with pytest.raises(ReadTimeout):
        driver.execute_and_read(expected_points=3, timeout_s=1)
    driver.zero()
    driver.disconnect()
    assert spy.sent == ["XE", "AB", "DZ", "CL"]


def test_device_clear_ends_a_pending_measurement() -> None:
    driver, spy = _driver(reads=[ReadTimeout("no data")])
    with pytest.raises(ReadTimeout):
        driver.execute_and_read(expected_points=3, timeout_s=1)
    driver.device_clear()
    assert not driver.measurement_pending
    assert ("device_clear", "") in spy.log


@pytest.mark.parametrize(("points", "timeout"), [(0, 1.0), (True, 1.0), (3, 0.0), (3, float("nan")), (3, -1.0)])
def test_execute_and_read_argument_checks(points: object, timeout: float) -> None:
    driver, spy = _driver()
    with pytest.raises(ValueError):
        driver.execute_and_read(expected_points=points, timeout_s=timeout)  # type: ignore[arg-type]
    assert spy.sent == []


def test_every_write_is_a_single_command() -> None:
    driver, spy = _driver(reads=[STAIRCASE.wire], answers={"ERRX?": '0,"No Error."', "*IDN?": "a,B1500A,0,x"})
    driver.identify()
    driver.set_format()
    driver.enable([1, 3])
    driver.force_v(3, 0.05, icomp=1e-3)
    driver.staircase_v(
        StaircaseSetup(channel=1, start=0.0, stop=3.0, points=3, icomp=1e-6, measure=(1, 3), operation={3: 1})
    )
    driver.execute_and_read(expected_points=9, timeout_s=5)
    driver.abort()
    driver.zero()
    driver.disconnect()
    driver.errors()
    assert all(";" not in cmd for cmd in spy.sent)
    assert spy.sent.count("AB") == 1


def test_auto_calibration_is_read_with_lrn_31_and_set_with_cm() -> None:
    driver, spy = _driver(answers={"*LRN? 31": "TM1;AV1,0;CM1;FMT1,0"})
    assert driver.auto_calibration() is True
    driver.set_auto_calibration(False)
    driver.set_auto_calibration(True)
    assert spy.sent == ["*LRN? 31", "CM 0", "CM 1"]


def test_auto_calibration_answer_without_cm_raises() -> None:
    driver, _ = _driver(answers={"*LRN? 31": "TM1;AV1,0;FMT1,0"})
    with pytest.raises(FlexParseError):
        driver.auto_calibration()
