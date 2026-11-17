"""OutputGuard (blueprint 2.3) and guard-spy tests: a refused source operation writes nothing to the transport."""

from __future__ import annotations

import math

import pytest

from b1500_test_agent.driver.b1500 import B1500Driver, StaircaseSetup
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from tests.unit.driver_helpers import SpyTransport, envelope

ENV = envelope(ch1=(3.0, 1e-6), ch3=(0.1, 1e-3), ch4=(0.0, 1e-3))


def _guarded() -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport()
    return B1500Driver(spy, OutputGuard(ENV)), spy


def _sweep(**overrides: object) -> StaircaseSetup:
    values: dict[str, object] = {"channel": 1, "start": -1.0, "stop": 3.0, "points": 41, "icomp": 1e-6, "measure": (3,)}
    values.update(overrides)
    return StaircaseSetup.model_validate(values)


# -- OutputGuard ------------------------------------------------------------------------------------------------


def test_guard_accepts_values_on_the_envelope_edge() -> None:
    guard = OutputGuard(ENV)
    guard.check(1, "V", 3.0, 1e-6)
    guard.check(1, "V", -3.0, -1e-6)
    guard.check(101, "V", 0.0, 1e-6)  # 101 and 1 are the same channel (PG Table 4-1)
    guard.check(4, "V", 0.0, 1e-3)
    guard.check(3, "I", 1e-3, 0.1)  # current source: level in A, compliance in V
    guard.check_channel(301)


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ((2, "V", 0.0, 1e-6), "channel_not_allowed"),
        ((102, "V", 0.0, 1e-6), "channel_not_allowed"),
        ((1, "V", 3.0000001, 1e-6), "level_exceeds_envelope"),
        ((1, "V", -3.5, 1e-6), "level_exceeds_envelope"),
        ((4, "V", 0.001, 1e-3), "level_exceeds_envelope"),
        ((1, "V", 1.0, 0.0), "zero_compliance"),
        ((1, "V", 1.0, 1.1e-6), "compliance_exceeds_envelope"),
        ((1, "V", 1.0, -2e-6), "compliance_exceeds_envelope"),
        ((3, "I", 2e-3, 0.1), "level_exceeds_envelope"),
        ((3, "I", 1e-3, 0.2), "compliance_exceeds_envelope"),
        ((1, "V", math.nan, 1e-6), "non_finite"),
        ((1, "V", 1.0, math.inf), "non_finite"),
    ],
)
def test_guard_refusals(args: tuple, reason: str) -> None:
    with pytest.raises(EnvelopeViolation) as info:
        OutputGuard(ENV).check(*args)
    assert info.value.reason == reason
    assert info.value.channel == args[0]


def test_guard_rejects_unknown_quantity() -> None:
    with pytest.raises(ValueError):
        OutputGuard(ENV).check(1, "P", 1.0, 1e-6)  # type: ignore[arg-type]


def test_violation_is_a_runtime_error_with_details() -> None:
    with pytest.raises(RuntimeError) as info:
        OutputGuard(ENV).check(1, "V", 5.0, 1e-6)
    violation = info.value
    assert isinstance(violation, EnvelopeViolation)
    assert (violation.quantity, violation.level, violation.compliance, violation.limit) == ("V", 5.0, 1e-6, 3.0)


# -- guard spy: nothing reaches the transport ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (lambda d: d.force_v(2, 0.5, icomp=1e-6), "channel_not_allowed"),
        (lambda d: d.force_v(3, 0.2, icomp=1e-6), "level_exceeds_envelope"),
        (lambda d: d.force_v(3, 0.05, icomp=2e-3), "compliance_exceeds_envelope"),
        (lambda d: d.force_v(3, 0.05, icomp=0.0), "zero_compliance"),
        (lambda d: d.enable([1, 2]), "channel_not_allowed"),
        (lambda d: d.staircase_v(_sweep(channel=2)), "channel_not_allowed"),
        (lambda d: d.staircase_v(_sweep(stop=3.5)), "level_exceeds_envelope"),
        (lambda d: d.staircase_v(_sweep(start=-4.0)), "level_exceeds_envelope"),
        (lambda d: d.staircase_v(_sweep(icomp=1e-5)), "compliance_exceeds_envelope"),
    ],
)
def test_violation_sends_nothing(action, reason: str) -> None:
    driver, spy = _guarded()
    with pytest.raises(EnvelopeViolation) as info:
        action(driver)
    assert info.value.reason == reason
    assert spy.sent == []


@pytest.mark.parametrize(
    "action",
    [
        lambda d: d.force_v(1, 0.5, icomp=1e-6),
        lambda d: d.enable([1]),
        lambda d: d.staircase_v(_sweep()),
    ],
)
def test_source_operations_refuse_without_a_guard(action) -> None:
    spy = SpyTransport()
    with pytest.raises(EnvelopeViolation) as info:
        action(B1500Driver(spy))
    assert info.value.reason == "no_guard"
    assert spy.sent == []


def test_allowed_source_operations_are_written() -> None:
    driver, spy = _guarded()
    driver.enable([1, 3])
    driver.force_v(3, 0.05, icomp=1e-3)
    driver.staircase_v(_sweep())
    assert spy.sent == ["CN 1,3", "DV 3,0,0.05,0.001", "MM 2,3", "WV 1,1,0,-1,3,41,1E-06", "WT 0,0", "WM 2,1"]


def test_cleanup_operations_never_need_a_guard() -> None:
    spy = SpyTransport(answers={"LOP?": "LOP00,00,00,00,00,00,00,00,00,00", "ERRX?": '0,"No Error."'})
    driver = B1500Driver(spy)
    driver.abort()
    driver.zero()
    driver.disconnect()
    driver.errors()
    driver.output_state()
    assert spy.sent == ["AB", "DZ", "CL", "ERRX?", "LOP?"]
