"""SMU sampling in the driver (WP7.4, blueprint v2 2.5): the ``MM 10`` builders and ``TSC``/``TSR`` (exact syntax per
the Programming Guide, domain checks), the timestamp parser ``driver/sampling.py`` against the golden fixtures, and
``SamplingOps`` (guard before any write, command order)."""

from __future__ import annotations

import pytest

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver, SamplingSetup, SamplingSource
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.parser import parse_data, parse_element
from b1500_test_agent.driver.sampling import parse_sampling
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from tests.unit.flex_fixtures import FIXTURE_DIR, load_fixture

# -- builders ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        (flex.mt(0.01, 0.001, 101, 0.1), "MT 0.01,0.001,101,0.1"),  # PG PDF 476 example
        (flex.mt(0, 0.0001, 5000, 0), "MT 0,0.0001,5000,0"),  # PG PDF 476 example
        (flex.mt(0.01, 0.004, 10001, 0.1), "MT 0.01,0.004,10001,0.1"),  # lwp IVt_sampling.m:39-40
        (flex.mt(-0.0005, 0.0005, 100, 0.01), "MT -0.0005,0.0005,100,0.01"),  # negative h_bias, fast sampling
        (flex.mv(1, 12, 0, 5, 1e-3), "MV 1,12,0,5,0.001"),  # PG PDF 478 example
        (flex.mv(3, 0, 0, 3, 0.01), "MV 3,0,0,3,0.01"),  # lwp IVt_sampling.m:53
        (flex.mi(1, 18, 0, 5e-5, 10), "MI 1,18,0,5E-05,10"),  # PG PDF 469 example
        (flex.mi(2, 0, -1e-6, -2e-6, 5), "MI 2,0,-1E-06,-2E-06,5"),
        (flex.ml(1), "ML 1"),
        (flex.ml(2), "ML 2"),  # PG PDF 470 example
        (flex.ml(7), "ML 7"),
        (flex.msc(True), "MSC 2"),  # PG PDF 473 example
        (flex.msc(True, "bias"), "MSC 2,2"),  # PG PDF 473 example
        (flex.msc(False, "base"), "MSC 1,1"),
        (flex.mcc(), "MCC"),  # PG PDF 461 example
        (flex.mcc([1, 2, 3]), "MCC 1,2,3"),  # PG PDF 461 example
        (flex.mm(10, [4]), "MM 10,4"),  # lwp IVt_sampling.m:58
        (flex.mm(10, [3, 4]), "MM 10,3,4"),
        (flex.tsc(True), "TSC 1"),  # PG PDF 539 example
        (flex.tsc(False), "TSC 0"),
        (flex.tsr(), "TSR"),  # PG PDF 540 example
        (flex.tsr(1), "TSR 1"),  # PG PDF 540 example
    ],
)
def test_sampling_builder_output(built: str, expected: str) -> None:
    assert built == expected


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.mt(0, 0.00009, 10, 0),  # interval below 100 us
        lambda: flex.mt(0, 65.536, 10, 0),
        lambda: flex.mt(0, 0.0025, 10, 0),  # off the 1 ms grid at >= 2 ms
        lambda: flex.mt(0, 0.000105, 10, 0),  # off the 10 us grid below 2 ms
        lambda: flex.mt(0.015, 0.01, 10, 0),  # h_bias off the 10 ms grid
        lambda: flex.mt(-0.001, 0.01, 10, 0),  # negative h_bias needs interval < 2 ms
        lambda: flex.mt(-0.1, 0.001, 10, 0),  # below -0.09 s
        lambda: flex.mt(655.36, 1, 10, 0),
        lambda: flex.mt(0, 1, 10, -0.01),
        lambda: flex.mt(0, 1, 10, 0.005),  # h_base off the 10 ms grid
        lambda: flex.mt(0, 1, 0, 0),
        lambda: flex.mt(0, 1, 100002, 0),
        lambda: flex.mt(0, float("nan"), 10, 0),
        lambda: flex.ml(0),
        lambda: flex.ml(8),
        lambda: flex.msc(True, "start"),
        lambda: flex.mcc(list(range(1, 11)) + [101, 201, 301, 401, 501, 601]),
        lambda: flex.mv(1, 0, 0, 1, 0),  # 0 A Icomp
        lambda: flex.mv(1, -20, 0, 1, 1e-3),  # no fixed output range codes
        lambda: flex.mv(1, 0, float("inf"), 1, 1e-3),
        lambda: flex.mv(11, 0, 0, 1, 1e-3),
        lambda: flex.mi(1, 18, -1e-6, 1e-6, 5),  # base and bias of opposite polarity
        lambda: flex.mi(1, 7, 0, 1e-6, 5),
        lambda: flex.tsr(11),
        lambda: flex.tsr(0),
        lambda: flex.mm(9, [1]),
    ],
)
def test_sampling_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize("call", [lambda: flex.mt(0, 1, 10.0, 0), lambda: flex.msc(2), lambda: flex.tsc(1),
                                  lambda: flex.ml(1.0), lambda: flex.tsr(True)])
def test_sampling_builders_reject_wrong_types(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_log_sampling_density_and_limits_follow_the_manual() -> None:
    """ML 2-7 = 10, 25, 50, 100, 250, 500 data per decade (PDF 470); log MT number <= 1 + data of 11 decades."""
    assert flex.LOG_SAMPLING_DENSITY == {2: 10, 3: 25, 4: 50, 5: 100, 6: 250, 7: 500}
    assert flex.LOG_SAMPLING_DECADES == 11 and flex.MT_MAX_NUMBER == 100001
    assert flex.SAMPLING_MODE == 10 and 10 in flex.MEASUREMENT_MODES


# -- timestamp parser --------------------------------------------------------------------------------------------


def _fixture_points(name: str) -> list:
    return parse_data(load_fixture(FIXTURE_DIR / name).body, 1)


def test_manual_example_block_is_index_then_data_per_channel() -> None:
    data = parse_sampling(_fixture_points("fmt1_sampling_manual_example.txt"), [3, 4])
    assert [s.index for s in data.samples] == [1, 2, 3] and data.trailing == 0
    assert data.has_index and not data.has_time
    assert [s.times for s in data.samples] == [(None, None)] * 3
    first = data.samples[0]
    assert [v.value for v in first.values] == pytest.approx([100e-6, 10e-6])
    assert [v.channel_number for v in first.values] == [3, 4] and not first.dummy


def test_time_stamps_and_the_dummy_data_after_an_automatic_abort() -> None:
    data = parse_sampling(_fixture_points("fmt1_sampling_tsc_abort.txt"), [4])
    assert data.has_index and data.has_time
    assert [s.index for s in data.samples] == [1, 2, 3, 4, 5]
    assert [s.time for s in data.samples] == pytest.approx([0.5, 1.5, 2.5, 3.5, 4.5])
    assert [s.dummy for s in data.samples] == [False, False, False, True, True]
    measured = data.measured
    assert len(measured) == 3 and str(measured[-1].values[0].status.value) == "C"


def test_index_gaps_are_kept() -> None:
    data = parse_sampling(_fixture_points("fmt1_sampling_index_gap.txt"), [3])
    assert [s.index for s in data.samples] == [2, 4]


def test_channels_101_and_1_are_one_channel_and_no_index_is_allowed() -> None:
    points = parse_data("NCI+1.00000E-06,NCI+2.00000E-06", 1)
    data = parse_sampling(points, [301])
    assert [s.index for s in data.samples] == [None, None] and not data.has_index


def test_an_incomplete_last_sample_is_trailing() -> None:
    points = parse_data("NCX+1.00000E+00,NCT+1.00000E-02,NCI+1.00000E-06,NDI+2.00000E-06,NCX+2.00000E+00,"
                        "NCT+2.00000E-02,NCI+1.00000E-06", 1)
    data = parse_sampling(points, [3, 4])
    assert len(data.samples) == 1 and data.trailing == 3
    assert data.samples[0].times == (0.01, None)  # SMU4's datum came without a time stamp


@pytest.mark.parametrize(
    ("text", "measure", "match"),
    [
        ("NCI+1.00000E-06,NDI+1.00000E-06", [4], "not the value of channel 4"),
        ("NCI+1.00000E-06,NDI+1.00000E-06", [4, 3], "not the value of channel 4"),
        ("WCV+1.00000E+00", [3], "no source data"),
        ("NCX+1.00000E+00,NCX+2.00000E+00,NCI+1.00000E-06", [3], "inside a sample"),
        ("NCX+1.00000E+00,NCI+1.00000E-06,NCX+2.00000E+00,NDI+1.00000E-06", [3, 4], "inside a sample"),
        ("NCT+1.00000E+00,NCT+2.00000E+00,NCI+1.00000E-06", [3], "two time stamps"),
        ("NCX+1.50000E+00,NCI+1.00000E-06", [3], "not a positive integer"),
        ("NCX+0.00000E+00,NCI+1.00000E-06", [3], "not a positive integer"),
        ("NCC+1.00000E-12", [3], "not the value of channel 3"),
    ],
)
def test_malformed_sampling_blocks_are_parse_errors(text: str, measure: list[int], match: str) -> None:
    with pytest.raises(FlexParseError, match=match):
        parse_sampling(parse_data(text, 1), measure)


def test_measure_must_name_a_channel() -> None:
    with pytest.raises(ValueError):
        parse_sampling([parse_element("NCI+1.00000E-06")], [])


# -- SamplingOps -------------------------------------------------------------------------------------------------


class Recorder:
    """A transport that records writes (no instrument behind it)."""

    backend = "sim"
    resource = "SIM::recorder"

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)


GATE, DRAIN = 3, 4
ENVELOPE = CompiledEnvelope(channels={
    GATE: ChannelEnvelope(role="gate", max_abs_v=3.0, max_abs_i=1e-6, function="bias_v", v_start=0.0, v_stop=3.0),
    DRAIN: ChannelEnvelope(role="drain", max_abs_v=5.0, max_abs_i=1e-3, function="bias_v", v_start=5.0, v_stop=5.0),
})
SETUP = SamplingSetup(h_bias=0.01, interval=0.004, number=10001, h_base=0.1,
                      sources=(SamplingSource(channel=GATE, quantity="V", base=0.0, bias=3.0, compliance=1e-6),),
                      measure=(DRAIN,), operation={DRAIN: 1})


def driver(guard: OutputGuard | None) -> tuple[B1500Driver, Recorder]:
    transport = Recorder()
    return B1500Driver(transport, guard), transport  # type: ignore[arg-type]


def test_sampling_setup_writes_the_mm10_sequence_in_order() -> None:
    drv, transport = driver(OutputGuard(ENVELOPE))
    drv.set_time_stamp(True)
    drv.sampling_setup(SETUP)
    drv.reset_timer()
    assert transport.writes == ["TSC 1", "MCC", "ML 1", "MT 0.01,0.004,10001,0.1", "MSC 2,2", "MV 3,0,0,3,1E-06",
                                "MM 10,4", "CMM 4,1", "TSR"]


def test_sampling_update_sends_only_what_changes_and_checks_the_sources() -> None:
    drv, transport = driver(OutputGuard(ENVELOPE))
    hold = SETUP.model_copy(update={"h_bias": 0.01, "h_base": 0.0, "number": 6250, "sources": (
        SETUP.sources[0].model_copy(update={"base": 3.0}),)})
    drv.sampling_update(hold, timing=True, sources=True)
    drv.sampling_update(hold, timing=False, sources=False)
    assert transport.writes == ["MT 0.01,0.004,6250,0", "MV 3,0,3,3,1E-06"]


@pytest.mark.parametrize(("base", "bias", "icomp"), [(0.0, 3.5, 1e-6), (-3.5, 3.0, 1e-6), (0.0, 3.0, 2e-6)])
def test_a_source_level_outside_the_envelope_sends_nothing(base: float, bias: float, icomp: float) -> None:
    drv, transport = driver(OutputGuard(ENVELOPE))
    bad = SETUP.model_copy(update={"sources": (
        SamplingSource(channel=GATE, quantity="V", base=base, bias=bias, compliance=icomp),)})
    with pytest.raises(EnvelopeViolation):
        drv.sampling_setup(bad)
    with pytest.raises(EnvelopeViolation):
        drv.sampling_update(bad, timing=True, sources=True)
    assert transport.writes == []


def test_a_current_source_is_checked_as_current_with_vcomp() -> None:
    envelope = CompiledEnvelope(channels={
        GATE: ChannelEnvelope(role="stress", max_abs_v=2.0, max_abs_i=1e-6, function="bias_i"),
        DRAIN: ENVELOPE.channels[DRAIN]})
    ok = SETUP.model_copy(update={"sources": (
        SamplingSource(channel=GATE, quantity="I", base=0.0, bias=1e-6, compliance=2.0),)})
    drv, transport = driver(OutputGuard(envelope))
    drv.sampling_setup(ok)
    assert "MI 3,0,0,1E-06,2" in transport.writes
    for source in (SamplingSource(channel=GATE, quantity="I", base=0.0, bias=2e-6, compliance=2.0),
                   SamplingSource(channel=GATE, quantity="I", base=0.0, bias=1e-6, compliance=3.0)):
        drv, transport = driver(OutputGuard(envelope))
        with pytest.raises(EnvelopeViolation):
            drv.sampling_setup(ok.model_copy(update={"sources": (source,)}))
        assert transport.writes == []


def test_without_a_guard_the_setup_is_refused_but_timers_are_not_sources() -> None:
    drv, transport = driver(None)
    with pytest.raises(EnvelopeViolation, match="no OutputGuard"):
        drv.sampling_setup(SETUP)
    drv.set_time_stamp(True)
    drv.reset_timer()
    assert transport.writes == ["TSC 1", "TSR"]
    sourceless = SETUP.model_copy(update={"sources": ()})
    drv.sampling_setup(sourceless)  # nothing to check: timing and measurement setup only
    assert transport.writes[-1] == "CMM 4,1"


@pytest.mark.parametrize("change", [
    {"mode": 8}, {"measure": (DRAIN, 401)}, {"operation": {GATE: 1}},
    {"sources": (SamplingSource(channel=GATE, quantity="V", base=0, bias=1, compliance=1e-6),
                 SamplingSource(channel=301, quantity="V", base=0, bias=1, compliance=1e-6))},
])
def test_inconsistent_setups_are_refused(change: dict) -> None:
    with pytest.raises(ValueError):
        SamplingSetup.model_validate({**SETUP.model_dump(), **change})


@pytest.mark.parametrize("fields", [
    {"quantity": "V", "base": 0, "bias": 1, "compliance": 0.0},
    {"quantity": "I", "base": -1e-6, "bias": 1e-6, "compliance": 2.0},
    {"quantity": "I", "base": 0, "bias": 1e-6, "compliance": 2.0, "range": 7},
])
def test_inconsistent_sources_are_refused(fields: dict) -> None:
    with pytest.raises(ValueError):
        SamplingSource(channel=GATE, **fields)
