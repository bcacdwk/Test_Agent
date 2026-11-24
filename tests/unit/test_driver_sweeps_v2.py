"""Driver sweep operations of WP7.2 (blueprint v2 2.5, 2.7): ``StaircaseSetup`` with a current primary (``WI``), a
synchronous source (``WSV``/``WSI``, MM 2) or multi-channel sources (``WNX``, MM 16), and the guarded ``force_i``
(``DI``). Every source level and compliance passes the guard before the first byte; a refusal writes nothing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from b1500_test_agent.driver.b1500 import B1500Driver, StaircaseSetup, SweepSource
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from tests.unit.driver_helpers import SpyTransport, envelope

pytestmark = pytest.mark.smu

# ch1: a voltage source (3 V, 1 mA); ch3: a current source (1 mA, 2 V); ch4/ch5: further sources
ENV = envelope(ch1=(3.0, 1e-3), ch3=(2.0, 1e-3), ch4=(1.5, 1e-4), ch5=(2.0, 1e-5))


def _driver() -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport()
    return B1500Driver(spy, OutputGuard(ENV)), spy


def _setup(**overrides: object) -> StaircaseSetup:
    values: dict[str, object] = {"channel": 1, "start": 0.0, "stop": 1.0, "points": 11, "icomp": 1e-3,
                                 "measure": (1,)}
    values.update(overrides)
    return StaircaseSetup.model_validate(values)


def test_a_v1_voltage_sweep_sends_the_v1_commands() -> None:
    driver, spy = _driver()
    driver.staircase_v(_setup(operation={1: 1}))
    assert spy.sent == ["MM 2,1", "CMM 1,1", "WV 1,1,0,0,1,11,0.001", "WT 0,0", "WM 2,1"]


def test_current_primary_sweep_sends_wi_with_its_voltage_compliance() -> None:
    driver, spy = _driver()
    setup = _setup(channel=3, source="I", icomp=None, vcomp=2.0, start=1e-9, stop=1e-3, points=61, sweep="log",
                   measure=(3,), operation={3: 2})
    driver.staircase(setup)
    assert spy.sent == ["MM 2,3", "CMM 3,2", "WI 3,2,0,1E-09,0.001,61,2", "WT 0,0", "WM 2,1"]
    assert setup.comp == 2.0 and setup.wv_mode == 2 and setup.mode == 2


def test_staircase_v_refuses_a_current_primary() -> None:
    driver, spy = _driver()
    with pytest.raises(ValueError, match="staircase sets a voltage|use staircase"):
        driver.staircase_v(_setup(channel=3, source="I", icomp=None, vcomp=2.0, start=0.0, stop=1e-3, measure=(3,)))
    assert spy.sent == []


def test_synchronous_voltage_source_follows_wv() -> None:
    driver, spy = _driver()
    sync = SweepSource(channel=4, source="V", start=0.2, stop=1.2, comp=1e-4)
    driver.staircase(_setup(double=True, sync=sync, measure=(1, 4)))
    assert spy.sent == ["MM 2,1,4", "WV 1,3,0,0,1,11,0.001", "WSV 4,0,0.2,1.2,0.0001", "WT 0,0", "WM 2,1"]


def test_synchronous_current_source_follows_wi() -> None:
    driver, spy = _driver()
    sync = SweepSource(channel=5, source="I", start=1e-7, stop=1e-5, comp=2.0)
    driver.staircase(_setup(channel=3, source="I", icomp=None, vcomp=2.0, start=1e-6, stop=1e-3, sweep="log",
                            sync=sync, measure=(3, 5)))
    assert spy.sent[1:3] == ["WI 3,2,0,1E-06,0.001,11,2", "WSI 5,0,1E-07,1E-05,2"]


def test_multi_channel_sweep_numbers_its_wnx_sources() -> None:
    driver, spy = _driver()
    sources = (SweepSource(channel=4, source="V", start=0.0, stop=-1.5, comp=1e-4, range=12),
               SweepSource(channel=3, source="I", start=0.0, stop=1e-3, comp=2.0))
    driver.staircase(_setup(multi_channel=True, sources=sources, measure=(1, 4, 3)))
    assert spy.sent == ["MM 16,1,4,3", "WV 1,1,0,0,1,11,0.001", "WNX 2,4,1,12,0,-1.5,0.0001",
                        "WNX 3,3,2,0,0,0.001,2", "WT 0,0", "WM 2,1"]


def test_a_multi_channel_sweep_may_have_the_primary_alone() -> None:
    """PG Table 3-13 (PDF 226-228) runs MM 16 with one WV source and DV biases."""
    driver, spy = _driver()
    driver.staircase(_setup(multi_channel=True, measure=(1,)))
    assert spy.sent[:2] == ["MM 16,1", "WV 1,1,0,0,1,11,0.001"]


@pytest.mark.parametrize(("sync", "sources", "field"), [
    (SweepSource(channel=5, source="I", start=0, stop=1e-6, comp=1), (), "the primary's output mode"),
    (None, (SweepSource(channel=4, source="V", start=0, stop=1, comp=1e-4),), "need multi_channel"),
    (SweepSource(channel=1, source="V", start=0, stop=1, comp=1e-4), (), "listed twice"),
])
def test_follower_rules(sync: SweepSource | None, sources: tuple[SweepSource, ...], field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        _setup(sync=sync, sources=sources)


@pytest.mark.parametrize("overrides", [
    {"icomp": None},  # a voltage sweep needs Icomp
    {"icomp": 0.0},
    {"vcomp": 1.0},  # Vcomp belongs to WI
    {"source": "I", "icomp": None, "vcomp": None},
    {"source": "I", "icomp": None, "vcomp": 2.0, "vrange": 12},  # vrange belongs to WV
    {"source": "I", "icomp": None, "vcomp": 2.0, "irange": -11},  # output ranging has no fixed codes
    {"sweep": "log", "start": 0.0},
    {"sweep": "log", "start": 0.1, "sync": {"channel": 4, "source": "V", "start": -0.1, "stop": 1, "comp": 1e-4}},
    {"multi_channel": True, "sync": {"channel": 4, "source": "V", "start": 0, "stop": 1, "comp": 1e-4}},
    {"multi_channel": True, "sources": [{"channel": c, "source": "V", "start": 0, "stop": 1, "comp": 1e-4}
                                        for c in (2, 3, 4, 5, 6, 7, 8, 9, 10, 201)]},  # ten WNX sources
])
def test_invalid_setups_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _setup(**overrides)


def test_sweep_source_checks_its_range_and_compliance() -> None:
    with pytest.raises(ValidationError, match="comp must be non-zero"):
        SweepSource(channel=4, source="V", start=0, stop=1, comp=0)
    with pytest.raises(ValidationError, match="output ranging code"):
        SweepSource(channel=4, source="I", start=0, stop=1e-6, comp=1, range=200)


@pytest.mark.parametrize(("setup", "reason"), [
    (lambda: _setup(stop=3.5), "level_exceeds_envelope"),  # primary end point
    (lambda: _setup(channel=3, source="I", icomp=None, vcomp=2.5, start=0.0, stop=1e-3, measure=(3,)),
     "compliance_exceeds_envelope"),  # Vcomp above the current source's |V|
    (lambda: _setup(channel=3, source="I", icomp=None, vcomp=2.0, start=0.0, stop=2e-3, measure=(3,)),
     "level_exceeds_envelope"),  # current above the current source's |I|
    (lambda: _setup(sync=SweepSource(channel=4, source="V", start=0, stop=1.6, comp=1e-4), measure=(1,)),
     "level_exceeds_envelope"),  # synchronous end point
    (lambda: _setup(multi_channel=True, sources=(SweepSource(channel=5, source="V", start=0, stop=1, comp=1e-3),),
                    measure=(1,)), "compliance_exceeds_envelope"),  # WNX compliance
    (lambda: _setup(multi_channel=True, sources=(SweepSource(channel=6, source="V", start=0, stop=1, comp=1e-6),),
                    measure=(1,)), "channel_not_allowed"),  # WNX channel outside the allowlist
])
def test_every_source_passes_the_guard_before_anything_is_written(setup, reason: str) -> None:
    driver, spy = _driver()
    with pytest.raises(EnvelopeViolation) as caught:
        driver.staircase(setup())
    assert caught.value.reason == reason and spy.sent == []


def test_force_i_is_guarded() -> None:
    driver, spy = _driver()
    driver.force_i(3, 5e-4, vcomp=2.0)
    assert spy.sent == ["DI 3,0,0.0005,2"]
    for call, reason in [(lambda: driver.force_i(3, 2e-3, vcomp=1.0), "level_exceeds_envelope"),
                         (lambda: driver.force_i(3, 1e-4, vcomp=5.0), "compliance_exceeds_envelope"),
                         (lambda: driver.force_i(6, 1e-6, vcomp=1.0), "channel_not_allowed")]:
        with pytest.raises(EnvelopeViolation) as caught:
            call()
        assert caught.value.reason == reason
    assert spy.sent == ["DI 3,0,0.0005,2"]
    unguarded = B1500Driver(SpyTransport())
    with pytest.raises(EnvelopeViolation) as caught:
        unguarded.force_i(3, 1e-6, vcomp=1.0)
    assert caught.value.reason == "no_guard"
