"""16440A selector FLEX builders (``driver/flex/switch.py``; WP6.1 ``ERSSP?``, WP9.2 ``ERMOD``/``ERSSP``): golden
strings from the Programming Guide (``tests/fixtures/flex/switch/builders.yaml``), the manual's parameter domains
(ports 0-3, states 0-3, PGU open only on CH 1 = ports 0 and 2, PG p154 (2-66); control modes of PG p419 (4-101))
and the state tables the driver and the simulator share."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex
from b1500_test_agent.models.routing import PGU_OPEN_PORTS, SWITCH_STATES

pytestmark = pytest.mark.spgu

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "switch" / "builders.yaml"
ENTRIES: list[dict[str, Any]] = [e for e in yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
                                 if e["builder"] in ("ermod", "erssp", "erssp_q")]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["expected"])
def test_golden_strings(entry: dict[str, Any]) -> None:
    assert getattr(flex, entry["builder"])(*entry["args"]) == entry["expected"]
    assert entry["page"].startswith("PG p")


def test_every_selector_builder_has_a_golden_string() -> None:
    assert {"ermod", "erssp", "erssp_q"} == {entry["builder"] for entry in ENTRIES}


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.ermod(3),  # not a control mode (0, 1, 2, 4, 8, 16, 32)
        lambda: flex.ermod(64),
        lambda: flex.ermod(1, 1),  # the option is a bool (enable/disable)
        lambda: flex.erssp(4, 0),  # ports 0-3
        lambda: flex.erssp(-1, 1),
        lambda: flex.erssp(0, 4),  # states 0-3
        lambda: flex.erssp(1, 3),  # PGU open: CH 1 only (ports 0 and 2)
        lambda: flex.erssp(3, 3),
        lambda: flex.erssp(True, 1),  # not an integer port
        lambda: flex.erssp_q(4),
    ],
)
def test_builders_refuse_values_outside_the_manual_domain(call: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        call()


def test_state_codes_are_the_manual_table_both_ways() -> None:
    assert flex.ERSSP_STATES == {0: "open", 1: "smu", 2: "pgu", 3: "pgu_open"}  # PG p433 (4-115)
    assert flex.ERSSP_CODES == {"open": 0, "smu": 1, "pgu": 2, "pgu_open": 3}
    assert set(flex.ERSSP_CODES) == SWITCH_STATES["selector_16440a"]
    assert flex.ERMOD_MODES == (0, 1, 2, 4, 8, 16, 32) and flex.ERMOD_SELECTOR == 1


@pytest.mark.parametrize("port", range(4))
def test_pgu_open_is_built_exactly_for_ch1_ports(port: int) -> None:
    if port in PGU_OPEN_PORTS:
        assert flex.erssp(port, 3) == f"ERSSP {port},3"
    else:
        with pytest.raises(ValueError, match="CH 1"):
            flex.erssp(port, 3)
