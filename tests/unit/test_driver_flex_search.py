"""SMU search and quasi-pulsed FLEX builders (``driver/flex/search.py``, WP7.5): golden strings from the Programming
Guide examples (``tests/fixtures/flex/search/builders.yaml``), the ``MM`` forms of modes 9, 14 and 15, the syntax
domains (BDV's 10 V span, step direction and count, timing grids, repeat counts) and what the builders refuse on
purpose (a zero compliance, a missing post value)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "search"
BUILDERS: dict[str, Any] = yaml.safe_load((FIXTURES / "builders.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", BUILDERS["cases"], ids=lambda c: f"{c['builder']}-{c['expect']}")
def test_builder_matches_the_golden_string(case: dict[str, Any]) -> None:
    built = getattr(flex, case["builder"])(*case["args"])
    assert built == case["expect"]
    assert 216 <= case["pdf"] <= 460  # the search examples and command pages of the Programming Guide
    manual = case.get("manual")
    if manual is not None:  # the manual's example, numerically equal (number forms differ)
        ours, theirs = built.split(" ", 1), manual.split(" ", 1)
        assert ours[0] == theirs[0]
        assert [float(a) for a in ours[1].split(",")] == [float(b) for b in theirs[1].replace(" ", "").split(",")]


def test_every_search_builder_has_a_golden_case() -> None:
    covered = {case["builder"] for case in BUILDERS["cases"]}
    assert covered == {"lsv", "lsi", "lgv", "lgi", "lsm", "lstm", "lssv", "lssi", "lsvm", "bsv", "bsi", "bgv", "bgi",
                       "bsm", "bst", "bssv", "bssi", "bsvm", "bdv", "bdt", "bdm"}


def test_measurement_mode_forms() -> None:
    """``MM 9[,chnum]`` takes at most one channel, ``MM 14`` and ``MM 15`` none (PG PDF 470)."""
    assert flex.mm(9, [3]) == "MM 9,3"  # Table 3-10 "MM 9,collector" (PDF 217)
    assert flex.mm(9, []) == "MM 9"
    assert flex.mm(14, []) == "MM 14" and flex.mm(15, []) == "MM 15"  # Tables 3-11/3-12 (PDF 220, 223)
    assert flex.SEARCH_MODES == {9, 14, 15} <= flex.MEASUREMENT_MODES
    for call in (lambda: flex.mm(9, [3, 4]), lambda: flex.mm(14, [3]), lambda: flex.mm(15, [3])):
        with pytest.raises(ValueError):
            call()


def test_linear_step_count_and_direction() -> None:
    assert flex.lsv(1, 0, 0, 10, 0.01, 1e-3) == "LSV 1,0,0,10,0.01,0.001"  # 1001 steps
    with pytest.raises(ValueError, match="1001"):
        flex.lsv(1, 0, 0, 10.01, 0.01, 1e-3)
    assert flex.lsv(1, 0, 0, -20, -0.1, 1e-3) == "LSV 1,0,0,-20,-0.1,0.001"
    with pytest.raises(ValueError, match="start to stop"):
        flex.lsv(1, 0, 0, -20, 0.1, 1e-3)


@pytest.mark.parametrize("call", [
    lambda: flex.bdv(1, 0, 0, 9.99, 1e-3),  # |start - stop| >= 10 V (PDF 365)
    lambda: flex.bdv(1, 0, 0, 101, 1e-3),  # MP/HRSMU +-100 V
    lambda: flex.bdv(1, 0, 0, 20, 0),  # Icomp always sent and not 0 A
    lambda: flex.bdv(1, 7, 0, 20, 1e-3),  # not a voltage range code
    lambda: flex.bdt(0.005, 0),  # hold off the 10 ms grid
    lambda: flex.bdt(0, 6.6),  # delay above 6.5535 s
    lambda: flex.bdm("medium", "V"),
    lambda: flex.bdm("short", "C"),
    lambda: flex.lstm(0, 65.6),  # delay above 65.535 s
    lambda: flex.bst(0, 0.00005),  # delay off the 0.1 ms grid
    lambda: flex.lsv(1, 0, 1, 1, 0.1, 1e-3),  # start = stop (error 276)
    lambda: flex.lsv(1, 0, 0, 1, 0, 1e-3),  # zero step
    lambda: flex.lsi(1, -12, 0, 1e-6, 1e-8, 5),  # output ranging has no fixed codes
    lambda: flex.lsi(1, 0, 0, 0.2, 0.01, 5),  # +-0.1 A
    lambda: flex.lgi(1, "rising", 0, 1e-6),
    lambda: flex.lgi(1, "above", 7, 1e-6),
    lambda: flex.lgv(1, "above", 0, 101),
    lambda: flex.bgi(1, 0, 0, 0, 1e-6),  # limit must be positive
    lambda: flex.bgi(1, 1, 17, 0, 1e-6),  # repeat 1-16
    lambda: flex.bgi(1, 1, 2.5, 0, 1e-6),
    lambda: flex.bgi(1, 2, 1, 0, 1e-6),  # mode 0 or 1
    lambda: flex.bsv(1, 0, 2, 2, 1e-3),
    lambda: flex.bsi(1, 0, 0, 1e-6, 0),
    lambda: flex.lssv(1, 0, 0, 1e-3),  # polarity +1 or -1
    lambda: flex.bssv(1, 1, 0, 0),
    lambda: flex.lsm(True, "end"),
    lambda: flex.bsm("fast", True, "start"),
])
def test_search_builders_reject_values_outside_the_manual_domain(call: Any) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize("call", [lambda: flex.lsm(2, "start"), lambda: flex.bsm("normal", 1, "start"),
                                  lambda: flex.lsvm(1), lambda: flex.bsvm(0), lambda: flex.lssv(1, True, 0, 1e-3)])
def test_search_builders_reject_wrong_types(call: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        call()


def test_no_search_builder_combines_commands() -> None:
    samples = [flex.lsv(1, 0, 0, 1, 0.1, 1e-3), flex.bsv(1, 0, 0, 1, 1e-3), flex.bdv(1, 0, 0, 10, 1e-3),
               flex.lgi(1, "above", 0, 1e-6), flex.bgi(1, 0, 1e-9, 0, 1e-7), flex.bsm("normal", True, "stop")]
    assert all(";" not in text and "\n" not in text for text in samples)
