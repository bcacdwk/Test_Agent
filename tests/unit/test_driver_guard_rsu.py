"""OutputGuard: the RSU "From SMU" input limit (WP21.13; WG p20 (1-8) "Or the RSU will be damaged" above +-25 V at
the From SMU input, WG p16 (1-4) "Maximum current: 100 mA").

An SMU the station records on an RSU's ``smu`` input is held to ``WGFMU_SPEC.smu_mode_max_v``/``smu_mode_max_a`` on top
of its (wider) compiled envelope, whatever the RSU's state: ``check`` (forced level and compliance, V and I forcing,
either channel numbering), ``check_pulse`` (SMU pulses) and ``check_route`` (an RSU switched to its SMU path, the WGFMU
channel in SMU mode). Refusals reach neither the FLEX transport (B1500Driver over a spy) nor the WGFMU library."""

from __future__ import annotations

from typing import Any

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver, StaircaseSetup
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.driver.modules import WGFMU_SPEC
from b1500_test_agent.driver.wgfmu import WgfmuDriver
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope, PulseEnvelope
from b1500_test_agent.models.routing import Route, rsu_inputs_of, rsu_smu_inputs, same_channel
from b1500_test_agent.models.sources import ChannelSetup
from tests.unit.driver_helpers import SpyTransport
from tests.unit.rules_factory_v2 import lab_station
from tests.unit.test_driver_wgfmu import FakeApi

pytestmark = pytest.mark.wgfmu

WIDE_PULSE = PulseEnvelope(max_abs_v_dut=40.0, min_width_s=1e-3, max_width_s=1e-3, max_duty=0.5, max_count=10,
                           max_on_time_s=1.0, max_short_circuit_a=0.1)
RSU201_SMU = Route(switch="RSU201", output="OUT", state="smu")
RSU202_SMU = Route(switch="RSU202", output="OUT", state="smu")
ENV = CompiledEnvelope(
    channels={
        3: ChannelEnvelope(role="drain", max_abs_v=40.0, max_abs_i=0.1, function="bias_v"),   # on RSU202's input
        4: ChannelEnvelope(role="gate", max_abs_v=40.0, max_abs_i=0.1, function="sweep_v"),   # on no RSU
        5: ChannelEnvelope(role="bulk", max_abs_v=40.0, max_abs_i=0.1, function="pulse_v", pulse=WIDE_PULSE),
        201: ChannelEnvelope(role="top", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
        202: ChannelEnvelope(role="bottom", max_abs_v=3.0, max_abs_i=None, function="wgfmu"),
    },
    routes=frozenset({RSU201_SMU, RSU202_SMU}),
)
"""A deliberately wide envelope (40 V, 100 mA: what a stale or buggy plan could carry): the guard's RSU check alone
must stop the levels the From SMU input cannot take."""
STATION = lab_station(rsu_smu={201: None, 202: 3})
"""SMU3 on RSU202's From SMU input; RSU201's input unknown (``null``)."""
V_MAX, A_MAX = WGFMU_SPEC.smu_mode_max_v, WGFMU_SPEC.smu_mode_max_a


def guard(envelope: CompiledEnvelope = ENV, station: Any = STATION) -> OutputGuard:
    return OutputGuard(envelope, switches=station.switches)


def test_the_limits_are_the_manual_values() -> None:
    assert (V_MAX, A_MAX) == (25.0, 0.1)
    assert "WG p20 (1-8)" in WGFMU_SPEC.sources


def test_the_station_lists_the_from_smu_inputs() -> None:
    assert [(i.target, i.channel) for i in rsu_smu_inputs(STATION.switches)] == [("RSU201.OUT", None),
                                                                                  ("RSU202.OUT", 3)]
    assert [i.target for i in rsu_inputs_of(STATION.switches, 301)] == ["RSU202.OUT"]  # 3 and 301: one channel
    assert rsu_inputs_of(STATION.switches, 4) == [] and same_channel(3, 301) and not same_channel(3, 4)
    absent = lab_station(rsu_smu={202: 3}, rsu={"present": False})
    assert rsu_smu_inputs(absent.switches) == []  # an RSU recorded absent has no input
    assert rsu_smu_inputs(lab_station().switches) == []  # no smu side: nothing cabled


# -- check (DC sources) ----------------------------------------------------------------------------------------------


def test_levels_within_the_input_pass() -> None:
    g = guard()
    g.check(3, "V", 25.0, 0.1)  # equal to the limits passes (limits are exclusive)
    g.check(3, "V", -25.0, 1e-3)
    g.check(301, "V", 24.0, 1e-3)  # 3 and 301 address the same SMU
    g.check(3, "I", 0.1, 25.0)
    g.check(4, "V", 40.0, 0.1)  # SMU4 is on no RSU: only its envelope applies
    guard(station=lab_station()).check(3, "V", 40.0, 0.1)  # nothing cabled to any From SMU input


@pytest.mark.parametrize(
    ("ch", "quantity", "level", "compliance", "limit"),
    [
        (3, "V", 25.5, 1e-3, V_MAX),     # forced voltage
        (3, "V", -30.0, 1e-3, V_MAX),    # either polarity
        (301, "V", 26.0, 1e-3, V_MAX),   # the n*100+1 channel number
        (3, "I", 1e-3, 30.0, V_MAX),     # a current source's voltage compliance
        (3, "I", -0.05, -26.0, V_MAX),   # a negative compliance counts by its magnitude
    ],
)
def test_levels_beyond_the_input_are_refused(ch: int, quantity: str, level: float, compliance: float,
                                             limit: float) -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check(ch, quantity, level, compliance)  # type: ignore[arg-type]
    assert caught.value.reason == "rsu_input_exceeded" and caught.value.limit == limit
    assert caught.value.channel == ch and "RSU202.OUT" in str(caught.value) and "WG p20 (1-8)" in str(caught.value)


def test_current_beyond_the_smu_path_is_refused() -> None:
    """100 mA is also the code ceiling, so a wider envelope (a test object) shows the RSU check on its own."""
    env = ENV.model_copy(update={"channels": {**ENV.channels, 3: ChannelEnvelope(role="drain", max_abs_v=40.0,
                                                                                 max_abs_i=0.5)}})
    for quantity, level, compliance in (("V", 1.0, 0.2), ("I", 0.2, 1.0)):
        with pytest.raises(EnvelopeViolation) as caught:
            guard(env).check(3, quantity, level, compliance)  # type: ignore[arg-type]
        assert caught.value.reason == "rsu_input_exceeded" and caught.value.limit == A_MAX
        assert "WG p16 (1-4)" in str(caught.value)


def test_the_envelope_is_checked_first() -> None:
    narrow = ENV.model_copy(update={"channels": {**ENV.channels, 3: ChannelEnvelope(role="drain", max_abs_v=2.0,
                                                                                    max_abs_i=1e-3)}})
    with pytest.raises(EnvelopeViolation) as caught:
        guard(narrow).check(3, "V", 30.0, 1e-3)
    assert caught.value.reason == "level_exceeds_envelope"


# -- check_pulse (SMU pulses) ----------------------------------------------------------------------------------------


def test_an_smu_pulse_on_an_rsu_input_is_held_to_25_v() -> None:
    on_rsu = lab_station(rsu_smu={202: 5})
    g = guard(station=on_rsu)
    g.check_pulse(5, 0.0, 25.0, 1e-3, 1e-2, 10, None)
    for base, peak in ((0.0, 25.5), (-26.0, 0.0)):
        with pytest.raises(EnvelopeViolation) as caught:
            g.check_pulse(5, base, peak, 1e-3, 1e-2, 10, None)
        assert caught.value.reason == "rsu_input_exceeded" and caught.value.quantity == "V_dut"
    guard().check_pulse(5, 0.0, 40.0, 1e-3, 1e-2, 10, None)  # SMU5 is on no RSU in STATION


# -- check_route (RSU on its SMU path) -------------------------------------------------------------------------------


def test_an_rsu_smu_path_needs_its_input_recorded_and_within_limits() -> None:
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_route(RSU202_SMU)  # SMU3's envelope (40 V) exceeds the input
    assert caught.value.reason == "rsu_input_exceeded" and caught.value.channel == 3
    with pytest.raises(EnvelopeViolation) as caught:
        guard().check_route(RSU201_SMU)  # the SMU on RSU201's input is unknown
    assert caught.value.reason == "route_not_allowed" and "unknown" in str(caught.value)
    within = ENV.model_copy(update={"channels": {**ENV.channels, 3: ChannelEnvelope(role="drain", max_abs_v=5.0,
                                                                                    max_abs_i=1e-3)}})
    guard(within).check_route(RSU202_SMU)
    not_in_plan = ENV.model_copy(update={"channels": {k: v for k, v in ENV.channels.items() if k != 3}})
    guard(not_in_plan).check_route(RSU202_SMU)  # SMU3 is no plan channel: the allowlist keeps it off
    guard(station=lab_station()).check_route(RSU202_SMU)  # nothing cabled: the SMU path floats the terminal


def test_rest_routes_always_pass() -> None:
    """The cleanup returns an RSU to its rest path whatever its input (an RSU resting on its SMU path too)."""
    guard().check_route(Route(switch="RSU201", output="OUT", state="open"))
    resting = lab_station(rsu_smu={201: None, 202: 3}, rsu={"rest": "smu"})
    for env in (ENV, CompiledEnvelope(channels={})):
        guard(env, resting).check_route(RSU201_SMU)
        guard(env, resting).check_route(RSU202_SMU)


# -- nothing reaches the transport or the library ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        lambda d: d.force_v(3, 26.0, icomp=1e-3),
        lambda d: d.force_i(3, 1e-3, vcomp=30.0),
        lambda d: d.staircase_v(StaircaseSetup(channel=3, start=0.0, stop=30.0, points=11, icomp=1e-3, measure=(3,))),
    ],
)
def test_refused_smu_operations_send_nothing(action: Any) -> None:
    spy = SpyTransport()
    with pytest.raises(EnvelopeViolation) as caught:
        action(B1500Driver(spy, guard()))
    assert caught.value.reason == "rsu_input_exceeded" and spy.sent == []


def test_allowed_smu_operations_are_written() -> None:
    spy = SpyTransport()
    B1500Driver(spy, guard()).force_v(3, 25.0, icomp=1e-3)
    assert spy.sent == ["DV 3,0,25,0.001"]


def test_a_wgfmu_channel_in_smu_mode_cannot_connect_an_over_limit_smu() -> None:
    """``WgfmuDriver.connect`` in SMU mode routes the RSU to ``smu`` through ``check_route``: refused before the
    library's ``connect`` when SMU3's envelope exceeds RSU202's input or RSU201's input is unknown."""
    for ch, reason in ((202, "rsu_input_exceeded"), (201, "route_not_allowed")):
        fake = FakeApi()
        wg = WgfmuDriver(fake, guard())  # type: ignore[arg-type]
        wg.configure(ch, ChannelSetup(mode="smu"))
        fake.calls.clear()
        with pytest.raises(EnvelopeViolation) as caught:
            wg.connect(ch)
        assert caught.value.reason == reason and fake.calls == [] and wg.connected == frozenset()
