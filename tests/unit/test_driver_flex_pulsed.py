"""SMU pulsed FLEX builders (``driver/flex/pulsed.py``, WP7.3): golden strings from the Programming Guide examples
(``tests/fixtures/flex/pulsed/builders.yaml``), the syntax domains (PT/MCPT timing, polarity of current pulses, log
pulsed sweeps), and what the builders refuse on purpose (automatic periods, a missing compliance)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "pulsed"
BUILDERS: dict[str, Any] = yaml.safe_load((FIXTURES / "builders.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", BUILDERS["cases"], ids=lambda c: f"{c['builder']}-{c['expect']}")
def test_builder_matches_the_golden_string(case: dict[str, Any]) -> None:
    built = getattr(flex, case["builder"])(*case["args"])
    assert built == case["expect"]
    assert 93 <= case["pdf"] <= 493  # the pulsed chapters, examples and command pages of the Programming Guide
    manual = case.get("manual")
    if manual is not None:  # the manual's example, numerically equal (blanks and number forms differ)
        ours, theirs = built.split(" ", 1), manual.split(" ", 1)
        assert ours[0] == theirs[0]
        assert [float(a) for a in ours[1].split(",")] == [float(b) for b in theirs[1].replace(" ", "").split(",")]


def test_the_period_rule_of_pt_and_mcpt() -> None:
    assert flex.pt(0, 0.1, 0.102) == "PT 0,0.1,0.102"  # width <= 100 ms: + 2 ms
    with pytest.raises(ValueError, match="2 ms"):
        flex.pt(0, 0.1, 0.1019)
    assert flex.pt(0, 0.2, 0.21) == "PT 0,0.2,0.21"  # above 100 ms: + 10 ms
    with pytest.raises(ValueError, match="10 ms"):
        flex.pt(0, 0.2, 0.205)
    assert flex.mcpt(0, 0.012, t0=0.01) == "MCPT 0,0.012"
    with pytest.raises(ValueError):
        flex.mcpt(0, 0.011, t0=0.01)


@pytest.mark.parametrize("call", [
    lambda: flex.pt(0, 0.001, 0),  # the automatic periods are never built
    lambda: flex.pt(0, 0.001, -1),
    lambda: flex.pt(0, 5e-6, 0.005),  # width below 10 us (any SMU type)
    lambda: flex.pt(0, 2.5, 5.0),  # width above 2 s
    lambda: flex.pt(0, 0.001, 6.0),  # period above 5 s
    lambda: flex.pt(0, 0.001, 0.00505),  # period off the 0.1 ms grid
    lambda: flex.pt(0.005, 0.001, 0.01),  # hold off the 10 ms grid
    lambda: flex.pt(0, 0.001, 0.01, 0.002),  # trigger delay beyond the width
    lambda: flex.pt(0, 0.0010001, 0.01),  # width off the 2 us grid
    lambda: flex.pv(1, 7, 0, 1, 1e-3),  # not a voltage range code
    lambda: flex.pv(1, 0, 0, 1, 0),  # Icomp always sent and non-zero
    lambda: flex.pi(1, 0, -1e-6, 1e-6, 1),  # current pulse of both polarities
    lambda: flex.pi(1, -12, 0, 1e-6, 1),  # output ranging has no fixed codes
    lambda: flex.pwv(1, 2, 0, 0, 0, 1, 11, 1e-3),  # log sweep through 0
    lambda: flex.pwv(1, 2, 0, -1, 0.1, 1, 11, 1e-3),  # log sweep with a base of the other polarity
    lambda: flex.pwv(1, 5, 0, 0, 0, 1, 11, 1e-3),  # sweep mode 1-4
    lambda: flex.pwv(1, 1, 0, 0, 0, 1, 10002, 1e-3),  # 1 to 10001 steps
    lambda: flex.pwi(1, 1, 0, 0, -1e-6, 1e-6, 11, 2),  # base/start/stop of one polarity
    lambda: flex.mcpt(0, 0.01, 1e-6),  # Mdelay below 2 us
    lambda: flex.mcpt(0, 0.01, 0, 1024),  # average 1-1023
    lambda: flex.mcpnt(1, -1e-6, 0.001),
    lambda: flex.mcpnx(11, 1, "V", 0, 0, 1, 1e-3),  # N 1-10
    lambda: flex.mcpnx(1, 1, "P", 0, 0, 1, 1e-3),
    lambda: flex.mcpnx(1, 1, "I", 0, -1e-6, 1e-6, 1),
    lambda: flex.mcpws(0, 11),
    lambda: flex.mcpwnx(1, 1, "V", 0, 0, 0, 1, 0),
])
def test_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


def test_the_pulsed_modes_and_mm() -> None:
    assert flex.PULSED_MODES == {3, 4, 5, 27, 28} and flex.PULSED_MODES <= flex.MEASUREMENT_MODES
    assert flex.mm(3, [1]) == "MM 3,1" and flex.mm(28, [1, 2, 3]) == "MM 28,1,2,3"
    assert flex.ait(flex.PULSE_ADC, flex.PULSE_ADC_TIME_MODE, 2e-4) == "AIT 2,3,0.0002"
    for mode in (3, 4, 5):
        with pytest.raises(ValueError):
            flex.mm(mode, [1, 2])
