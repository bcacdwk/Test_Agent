"""WP7.1 driver additions (blueprint v2 2.5): the ``DI`` builder and the ASU builders (``SAP``, ``SAR``, ``SAL``)
against golden strings per family (``tests/fixtures/flex/smu/``, ``tests/fixtures/flex/switch/``), their domain
checks, the ``*LRN? 62/63`` parsers and the guarded driver operations ``force_i``, ``spot_setup`` and the ASU
operations (``set_asu_path`` passes ``OutputGuard.check_route``; ``SAR``/``SAL`` change no output)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex
from b1500_test_agent.driver.b1500 import B1500Driver
from b1500_test_agent.driver.discovery import parse_asu_1pa, parse_asu_paths
from b1500_test_agent.driver.errors import FlexParseError
from b1500_test_agent.driver.guard import EnvelopeViolation, OutputGuard
from b1500_test_agent.models.plan import ChannelEnvelope, CompiledEnvelope
from b1500_test_agent.models.routing import Route, SwitchPort, SwitchSpec
from tests.unit.driver_helpers import SpyTransport

pytestmark = pytest.mark.smu

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex"


def _golden(family: str) -> list[dict[str, Any]]:
    return yaml.safe_load((FIXTURES / family / "builders.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", [*_golden("smu"), *_golden("switch")],
                         ids=lambda e: f"{e['builder']}-{'-'.join(str(a) for a in e['args'])}")
def test_builders_match_the_golden_strings(entry: dict[str, Any]) -> None:
    built = getattr(flex, entry["builder"])(*entry["args"])
    assert built == entry["expected"]
    assert ";" not in built
    page = int(entry["page"].split()[1].lstrip("p"))
    cited: set[int] = set()
    for first, last in re.findall(r"PDF (\d+)(?:-(\d+))?", getattr(flex, entry["builder"]).__doc__ or ""):
        cited.update(range(int(first), int(last or first) + 1))
    assert page in cited, f"{entry['builder']} docstring does not cite {entry['page']}"


@pytest.mark.parametrize(("call", "message"), [
    (lambda: flex.di(3, 7, 1e-3, 1.0), "DI irange"),
    (lambda: flex.di(3, 24, 1e-3, 1.0), "DI irange"),
    (lambda: flex.di(3, 0, 1e-3, 0), "Vcomp must not be 0"),
    (lambda: flex.di(11, 0, 1e-3, 1.0), "channel"),
    (lambda: flex.sap(3, 2), "SAP path"),
    (lambda: flex.sar(3, 2), "SAR mode"),
    (lambda: flex.sal(3, -1), "SAL mode"),
])
def test_builders_refuse_values_outside_the_manual_domain(call: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()


def test_asu_tables_follow_the_manual() -> None:
    """SAP path 0 = SMU side, 1 = AUX (PG p506 (4-188)); SAR 0 enables, 1 disables (initial) the 1 pA auto range."""
    assert flex.ASU_PATHS == {0: "smu", 1: "cmu"} and flex.ASU_PATH_CODES == {"smu": 0, "cmu": 1}
    assert (flex.SAR_ENABLE_1PA, flex.SAR_DISABLE_1PA) == (0, 1)
    assert (flex.LRN_ASU_PATH, flex.LRN_ASU_1PA) == (62, 63)


# -- *LRN? 62 / 63 ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("SAP3,0;SAP4,1", {3: "smu", 4: "cmu"}),
    ("SAP 3,0", {3: "smu"}),
    ("SAP 301,1", {3: "cmu"}),
    ("", {}),
    ("SAP", {}),
])
def test_asu_paths_parse(text: str, expected: dict[int, str]) -> None:
    assert parse_asu_paths(text) == expected


def test_asu_1pa_modes_parse() -> None:
    assert parse_asu_1pa("SAR3,0;SAR 4,1") == {3: True, 4: False}
    assert parse_asu_1pa("") == {}


@pytest.mark.parametrize("text", ["SAP3,2", "SAR3,0", "SAP3,0;SAP3,1", "SAP x,0", "CN3,4"])
def test_malformed_asu_answers_are_parse_errors(text: str) -> None:
    with pytest.raises(FlexParseError):
        parse_asu_paths(text)


# -- guarded operations ----------------------------------------------------------------------------------------------

ENVELOPE = CompiledEnvelope(channels={
    3: ChannelEnvelope(role="a", max_abs_v=1.0, max_abs_i=0.01, function="bias_i"),
    4: ChannelEnvelope(role="d", max_abs_v=2.0, max_abs_i=0.0, function="bias_i"),
})
ASU4 = SwitchSpec(id="ASU4", kind="asu", present=True, rest="smu",
                  ports={"OUT": SwitchPort(index=4, inputs={"smu": 4, "cmu": None})})


def _driver(*, guard: bool = True, answers: dict[str, str] | None = None) -> tuple[B1500Driver, SpyTransport]:
    spy = SpyTransport(answers=answers)
    return B1500Driver(spy, OutputGuard(ENVELOPE, switches=[ASU4]) if guard else None), spy  # type: ignore[arg-type]


def test_force_i_checks_current_and_voltage_compliance_before_writing() -> None:
    driver, spy = _driver()
    driver.force_i(3, -0.01, vcomp=1.0)
    driver.force_i(4, 0.0, vcomp=2.0)  # a voltmeter: 0 A with its voltage compliance
    assert spy.sent == ["DI 3,0,-0.01,1", "DI 4,0,0,2"]
    for kwargs, reason in (({"i": 0.02, "vcomp": 1.0}, "level_exceeds_envelope"),
                           ({"i": 0.005, "vcomp": 5.0}, "compliance_exceeds_envelope"),
                           ({"i": 0.005, "vcomp": 0.0}, "zero_compliance")):
        with pytest.raises(EnvelopeViolation) as caught:
            driver.force_i(3, kwargs["i"], vcomp=kwargs["vcomp"])
        assert caught.value.reason == reason
    with pytest.raises(EnvelopeViolation, match="not in the plan allowlist"):
        driver.force_i(5, 0.001, vcomp=1.0)
    assert spy.sent == ["DI 3,0,-0.01,1", "DI 4,0,0,2"]  # nothing refused reached the transport
    unguarded, spy2 = _driver(guard=False)
    with pytest.raises(EnvelopeViolation) as caught:
        unguarded.force_i(3, 0.001, vcomp=1.0)
    assert caught.value.reason == "no_guard" and spy2.sent == []


def test_spot_setup_writes_mm_1_and_the_measurement_modes() -> None:
    driver, spy = _driver(guard=False)  # not a source command: no guard needed
    driver.spot_setup([3, 4], {3: 2, 4: 1})
    assert spy.sent == ["MM 1,3,4", "CMM 3,2", "CMM 4,1"]
    with pytest.raises(ValueError, match="not measured"):
        driver.spot_setup([3], {4: 1})


def test_asu_path_is_a_guarded_route() -> None:
    driver, spy = _driver()
    driver.set_asu_path(Route(switch="ASU4", output="OUT", state="smu"), 4)  # the rest state: always allowed
    assert spy.sent == ["SAP 4,0"]
    with pytest.raises(EnvelopeViolation) as caught:  # AUX is no route of this plan
        driver.set_asu_path(Route(switch="ASU4", output="OUT", state="cmu"), 4)
    assert caught.value.reason == "route_not_allowed" and spy.sent == ["SAP 4,0"]
    with pytest.raises(ValueError, match="no state"):
        driver.set_asu_path(Route(switch="ASU4", output="OUT", state="pgu"), 4)
    allowed = CompiledEnvelope(channels=ENVELOPE.channels, routes=frozenset({Route(switch="ASU4", output="OUT",
                                                                                   state="cmu")}))
    routed = B1500Driver(spy, OutputGuard(allowed, switches=[ASU4]))  # type: ignore[arg-type]
    routed.set_asu_path(Route(switch="ASU4", output="OUT", state="cmu"), 4)
    assert spy.sent[-1] == "SAP 4,1"


def test_asu_ranging_and_indicator_need_no_guard_and_queries_parse() -> None:
    driver, spy = _driver(guard=False, answers={"*LRN? 62": "SAP4,0", "*LRN? 63": "SAR4,0"})
    driver.set_asu_1pa_auto(4, True)
    driver.set_asu_1pa_auto(4, False)
    driver.set_asu_indicator(4, False)
    assert spy.sent == ["SAR 4,0", "SAR 4,1", "SAL 4,0"]
    assert driver.asu_paths() == {4: "smu"} and driver.asu_1pa_auto() == {4: True}
