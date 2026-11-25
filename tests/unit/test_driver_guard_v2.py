"""OutputGuard v2 (blueprint v2 2.5): ``check_pulse``, ``check_ac``, ``check_route``, ``check_waveform`` refusal
tables, and guard-spy tests: an operation the guard refuses writes nothing to the FLEX transport and calls nothing on
the WGFMU library. The spy operations below follow the contract the family mixins (``ops/spgu.py``, ``ops/cmu.py``,
``ops/switch.py``, ``driver/wgfmu.py``) implement: guard first, then the transport."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pytest

from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.ops.core import DriverBase
from b1500_test_agent.models.plan import AcEnvelope, ChannelEnvelope, CompiledEnvelope, PulseEnvelope, WaveformLimits
from b1500_test_agent.models.routing import Route
from b1500_test_agent.models.sources import PulseTrain, pulse_envelope
from tests.unit.driver_helpers import SpyTransport
from tests.unit.rules_factory_v2 import lab_station

TRAIN = PulseTrain(base_v=0.0, peak_v=4.0, width_s=1e-6, period_s=1e-4, count=1000, load_ohm=1e6)
SPGU_PULSE = pulse_envelope([TRAIN], source_ohm=50.0)
SMU_PULSE = pulse_envelope([PulseTrain(base_v=0.0, peak_v=2.0, width_s=1e-3, period_s=1e-2, count=10)],
                           source_ohm=None)
SEL1_PGU = Route(switch="SEL1", output="OUT1", state="pgu")
ENV = CompiledEnvelope(
    channels={
        101: ChannelEnvelope(role="gate", max_abs_v=SPGU_PULSE.max_abs_v_dut, max_abs_i=None, function="pgu",
                             pulse=SPGU_PULSE),
        102: ChannelEnvelope(role="aux", max_abs_v=4.0, max_abs_i=None, function="pgu"),
        5: ChannelEnvelope(role="drain", max_abs_v=2.0, max_abs_i=1e-3, function="pulse_v", pulse=SMU_PULSE),
        7: ChannelEnvelope(role="cmu", max_abs_v=2.0, max_abs_i=1e-6, function="cmu_high", v_start=-2.0, v_stop=2.0,
                           ac=AcEnvelope(max_vrms=0.03, max_dc_v=2.0, f_min_hz=1e3, f_max_hz=1e6)),
        201: ChannelEnvelope(role="top", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
        202: ChannelEnvelope(role="bottom", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
    },
    routes=frozenset({SEL1_PGU}),
    waveform={201: WaveformLimits(max_vectors=4, max_points=1000, total_time_s=1e-5)},
)


def guard(*, switches: bool = True) -> OutputGuard:
    return OutputGuard(ENV, switches=lab_station().switches if switches else ())


# -- check_pulse -----------------------------------------------------------------------------------------------------


@pytest.mark.spgu
def test_pulse_inside_the_envelope_passes() -> None:
    g = guard()
    g.check_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 1000, 1e6)  # the compiled train itself
    g.check_pulse(101, -2.0, 0.0, 1e-6, 1e-2, 1, 1e6)
    g.check_pulse(1, 0.0, 2.0, 1e-6, 1e-4, 10, 1e3)  # 1 and 101 are the same channel; 2.1 V open load
    g.check_pulse(5, 0.0, 2.0, 1e-3, 1e-2, 10, None)  # SMU pulse: set level, no SER


@pytest.mark.spgu
@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ((103, 0.0, 1.0, 1e-6, 1e-4, 1, 1e6), "channel_not_allowed"),
        ((102, 0.0, 1.0, 1e-6, 1e-4, 1, 1e6), "no_pulse_envelope"),
        ((201, 0.0, 1.0, 1e-6, 1e-4, 1, None), "no_pulse_envelope"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 0, 1e6), "free_run"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, -1, 1e6), "free_run"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, True, 1e6), "free_run"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 1.5, 1e6), "free_run"),
        ((101, 0.0, 4.0, 1e-4, 1e-4, 1, 1e6), "invalid_pulse"),
        ((101, 0.0, 4.0, 0.0, 1e-4, 1, 1e6), "invalid_pulse"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 1, None), "invalid_pulse"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 1, 0.0), "invalid_pulse"),
        ((5, 0.0, 2.0, 1e-3, 1e-2, 1, 50.0), "invalid_pulse"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 1, 50.0), "pulse_level_exceeds_envelope"),  # SER 50: 8 V at an open load
        ((101, 0.0, -4.1, 1e-6, 1e-4, 1, 1e6), "pulse_level_exceeds_envelope"),
        ((101, 4.1, 0.0, 1e-6, 1e-4, 1, 1e6), "pulse_level_exceeds_envelope"),
        ((5, 0.0, 2.5, 1e-3, 1e-2, 1, None), "pulse_level_exceeds_envelope"),
        ((101, 0.0, 4.0, 2e-6, 1e-4, 1, 1e6), "pulse_width_outside_envelope"),
        ((101, 0.0, 4.0, 5e-7, 1e-4, 1, 1e6), "pulse_width_outside_envelope"),
        ((101, 0.0, 4.0, 1e-6, 5e-5, 1, 1e6), "duty_exceeds_envelope"),
        ((101, 0.0, 4.0, 1e-6, 1e-4, 1001, 1e6), "count_exceeds_envelope"),
        ((5, 0.0, 2.0, 1e-3, 1e-2, 11, None), "count_exceeds_envelope"),
        ((101, 0.0, math.nan, 1e-6, 1e-4, 1, 1e6), "non_finite"),
        ((101, 0.0, 4.0, 1e-6, math.inf, 1, 1e6), "non_finite"),
    ],
)
def test_pulse_refusals(args: tuple[Any, ...], reason: str) -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_pulse(*args)
    assert caught.value.reason == reason


@pytest.mark.spgu
def test_pulse_on_time_is_bounded_per_start() -> None:
    env = CompiledEnvelope(channels={101: ChannelEnvelope(
        role="gate", max_abs_v=5.0, max_abs_i=None, function="pgu",
        pulse=PulseEnvelope(max_abs_v_dut=5.0, min_width_s=1e-6, max_width_s=1e-3, max_duty=0.5, max_count=1000,
                            max_on_time_s=1e-2, max_short_circuit_a=0.1))})
    OutputGuard(env).check_pulse(101, 0.0, 2.0, 1e-3, 1e-2, 10, 1e6)  # 10 ms on-time: the limit
    with pytest.raises(EnvelopeViolation) as caught:
        OutputGuard(env).check_pulse(101, 0.0, 2.0, 1e-3, 1e-2, 11, 1e6)
    assert caught.value.reason == "on_time_exceeds_envelope" and caught.value.limit == 1e-2


@pytest.mark.spgu
def test_pulse_violation_reports_the_open_load_level() -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 1, 50.0)
    assert (caught.value.quantity, caught.value.level, caught.value.limit) == ("V_dut", 8.0,
                                                                                SPGU_PULSE.max_abs_v_dut)


# -- check_ac --------------------------------------------------------------------------------------------------------


def test_ac_inside_the_envelope_passes() -> None:
    g = guard()
    g.check_ac(7, 0.03, -2.0, 1e3)
    g.check_ac(7, 0.0, 0.0, 1e6)


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ((3, 0.03, 0.0, 1e6), "channel_not_allowed"),
        ((5, 0.03, 0.0, 1e6), "no_ac_envelope"),
        ((7, 0.031, 0.0, 1e6), "ac_exceeds_envelope"),
        ((7, -0.01, 0.0, 1e6), "ac_exceeds_envelope"),
        ((7, 0.03, 2.5, 1e6), "dc_exceeds_envelope"),
        ((7, 0.03, -2.5, 1e6), "dc_exceeds_envelope"),
        ((7, 0.03, 0.0, 2e6), "frequency_outside_envelope"),
        ((7, 0.03, 0.0, 999.0), "frequency_outside_envelope"),
        ((7, math.nan, 0.0, 1e6), "non_finite"),
    ],
)
def test_ac_refusals(args: tuple[Any, ...], reason: str) -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_ac(*args)
    assert caught.value.reason == reason


# -- check_route -----------------------------------------------------------------------------------------------------


@pytest.mark.spgu
def test_routes_of_the_plan_and_rest_states_pass() -> None:
    g = guard()
    g.check_route(SEL1_PGU)
    g.check_route(Route(switch="SEL1", output="OUT1", state="open"))  # rest
    g.check_route(Route(switch="SEL2", output="OUT2", state="open"))  # rest of another declared switch
    g.check_route(Route(switch="SCUU1", output="OUT1", state="smu"))  # SCUU rest = smu
    guard(switches=False).check_route(SEL1_PGU)


@pytest.mark.spgu
@pytest.mark.parametrize(
    ("route", "switches"),
    [
        (Route(switch="SEL1", output="OUT1", state="smu"), True),       # not a route of the plan
        (Route(switch="SEL1", output="OUT2", state="pgu_open"), True),  # PGU-open only on CH 1
        (Route(switch="SEL1", output="OUT3", state="open"), True),      # undeclared output
        (Route(switch="SEL9", output="OUT1", state="open"), True),      # undeclared switch
        (Route(switch="SEL1", output="OUT1", state="open"), False),     # rest needs the declared switches
        (Route(switch="SCUU1", output="OUT1", state="cmu"), True),
    ],
)
def test_route_refusals(route: Route, switches: bool) -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard(switches=switches).check_route(route)
    assert caught.value.reason == "route_not_allowed"


@pytest.mark.spgu
def test_a_route_the_switch_cannot_take_is_refused_even_when_compiled() -> None:
    bad = Route(switch="SEL1", output="OUT2", state="pgu_open")
    env = ENV.model_copy(update={"routes": frozenset({bad})})
    with pytest.raises(EnvelopeViolation):
        OutputGuard(env, switches=lab_station().switches).check_route(bad)


# -- check_waveform --------------------------------------------------------------------------------------------------


@pytest.mark.wgfmu
def test_waveform_inside_the_envelope_passes() -> None:
    g = guard()
    g.check_waveform(201, [1e-6, 1e-6, 1e-6, 1e-6], [3.0, 0.0, -3.0, 0.0], v0=0.0)
    g.check_waveform(201, [1e-8], [3.0])


@pytest.mark.parametrize(
    ("ch", "dt", "v", "v0", "reason"),
    [
        (203, [1e-6], [1.0], None, "channel_not_allowed"),
        (202, [1e-6], [1.0], None, "no_waveform_envelope"),
        (201, [1e-6, 1e-6], [1.0], None, "invalid_waveform"),
        (201, [1e-6] * 5, [0.0] * 5, None, "vectors_exceed_envelope"),
        (201, [1e-6], [3.1], None, "level_exceeds_envelope"),
        (201, [1e-6], [0.0], -3.5, "level_exceeds_envelope"),
        (201, [1.5e-8], [0.0], None, "off_grid"),
        (201, [0.0], [0.0], None, "off_grid"),
        (201, [-1e-8], [0.0], None, "off_grid"),
        (201, [4e-6, 4e-6, 4e-6], [0.0, 1.0, 0.0], None, "time_exceeds_envelope"),
        (201, [1e-6], [math.nan], None, "non_finite"),
    ],
)
@pytest.mark.wgfmu
def test_waveform_refusals(ch: int, dt: list[float], v: list[float], v0: float | None, reason: str) -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_waveform(ch, dt, v, v0=v0)
    assert caught.value.reason == reason


# -- guard spy -------------------------------------------------------------------------------------------------------


class SpyOps(DriverBase):
    """Stand-in family operations with the v2 contract: guard check, then one command per write."""

    def configure_pulse(self, ch: int, base: float, peak: float, width: float, period: float, count: int,
                        load: float | None) -> None:
        self._require_guard("configure_pulse", ch).check_pulse(ch, base, peak, width, period, count, load)
        if load is not None:
            self._write(f"SER {ch},{load:g}")
        self._write(f"SPV {ch},1,{base:g},{peak:g}")
        self._write(f"SPRM 1,{count}")

    def set_ac(self, ch: int, vrms: float, dc: float, freq: float) -> None:
        self._require_guard("set_ac", ch).check_ac(ch, vrms, dc, freq)
        self._write(f"FC {ch},{freq:g}")
        self._write(f"ACV {ch},{vrms:g}")
        self._write(f"DCV {ch},{dc:g}")

    def route(self, route: Route, port: int, status: int) -> None:
        self._require_guard("route", port).check_route(route)
        self._write("ERMOD 1")
        self._write(f"ERSSP {port},{status}")


class SpyWgfmu:
    """Records every library call (the ``WgfmuApi`` shape)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def create_pattern(self, name: str, v0: float) -> None:
        self.calls.append(("create_pattern", (name, v0)))

    def add_vectors(self, name: str, dt: Sequence[float], v: Sequence[float]) -> None:
        self.calls.append(("add_vectors", (name, len(dt))))


def load_pattern(api: SpyWgfmu, g: OutputGuard, ch: int, name: str, v0: float, dt: list[float],
                 v: list[float]) -> None:
    """``WgfmuDriver.load`` contract: ``check_waveform`` on the pattern before any library call."""
    g.check_waveform(ch, dt, v, v0=v0)
    api.create_pattern(name, v0)
    api.add_vectors(name, dt, v)


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (lambda d: d.configure_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 1000, 50.0), "pulse_level_exceeds_envelope"),
        (lambda d: d.configure_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 0, 1e6), "free_run"),
        (lambda d: d.configure_pulse(102, 0.0, 1.0, 1e-6, 1e-4, 1, 1e6), "no_pulse_envelope"),
        (lambda d: d.set_ac(7, 0.3, 0.0, 1e6), "ac_exceeds_envelope"),
        (lambda d: d.set_ac(7, 0.03, 5.0, 1e6), "dc_exceeds_envelope"),
        (lambda d: d.set_ac(7, 0.03, 0.0, 1e7), "frequency_outside_envelope"),
        (lambda d: d.route(Route(switch="SEL1", output="OUT2", state="pgu_open"), 1, 3), "route_not_allowed"),
        (lambda d: d.route(Route(switch="SEL1", output="OUT1", state="smu"), 0, 1), "route_not_allowed"),
    ],
)
def test_refused_v2_operations_send_nothing(action: Any, reason: str) -> None:
    spy = SpyTransport()
    ops = SpyOps(spy, guard())
    with pytest.raises(EnvelopeViolation) as caught:
        action(ops)
    assert caught.value.reason == reason
    assert spy.sent == []


def test_v2_operations_refuse_without_a_guard() -> None:
    spy = SpyTransport()
    with pytest.raises(EnvelopeViolation) as caught:
        SpyOps(spy).configure_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 1000, 1e6)
    assert caught.value.reason == "no_guard" and spy.sent == []


def test_allowed_v2_operations_are_written() -> None:
    spy = SpyTransport()
    ops = SpyOps(spy, guard())
    ops.configure_pulse(101, 0.0, 4.0, 1e-6, 1e-4, 1000, 1e6)
    ops.set_ac(7, 0.03, -2.0, 1e6)
    ops.route(SEL1_PGU, 0, 2)
    assert spy.sent == ["SER 101,1e+06", "SPV 101,1,0,4", "SPRM 1,1000", "FC 7,1e+06", "ACV 7,0.03", "DCV 7,-2",
                        "ERMOD 1", "ERSSP 0,2"]


@pytest.mark.parametrize(
    ("dt", "v", "v0"),
    [([1.5e-8], [1.0], 0.0), ([1e-6], [3.5], 0.0), ([1e-6], [0.0], 4.0), ([1e-6] * 5, [0.0] * 5, 0.0)],
)
@pytest.mark.wgfmu
def test_refused_waveform_reaches_no_library_call(dt: list[float], v: list[float], v0: float) -> None:
    api = SpyWgfmu()
    with pytest.raises(EnvelopeViolation):
        load_pattern(api, guard(), 201, "p", v0, dt, v)
    assert api.calls == []


@pytest.mark.wgfmu
def test_allowed_waveform_reaches_the_library() -> None:
    api = SpyWgfmu()
    load_pattern(api, guard(), 201, "p", 0.0, [1e-6, 1e-6], [3.0, 0.0])
    assert api.calls == [("create_pattern", ("p", 0.0)), ("add_vectors", ("p", 2))]
