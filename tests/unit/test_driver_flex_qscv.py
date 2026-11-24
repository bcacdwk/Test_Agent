"""SMU quasi-static C-V FLEX builders (``driver/flex/qscv.py``, WP8.5): golden strings from the Programming Guide
examples (``tests/fixtures/flex/qscv/builders.yaml``), the ``MM 13[,chnum]`` form, the syntax domains (QSV mode, step
count, cvoltage, QST integration times and grids, QSR codes, QSZ modes) and what the builders refuse on purpose (a zero
compliance, a smart operation without its channel)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "qscv"
BUILDERS: dict[str, Any] = yaml.safe_load((FIXTURES / "builders.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", BUILDERS["cases"], ids=lambda c: f"{c['builder']}-{c['expect']}")
def test_builder_matches_the_golden_string(case: dict[str, Any]) -> None:
    built = getattr(flex, case["builder"])(*case["args"])
    assert built == case["expect"]
    assert 241 <= case["pdf"] <= 500  # the QSCV example and command pages of the Programming Guide
    manual = case.get("manual")
    if manual is not None:  # the manual's example, numerically equal (number forms differ)
        ours, theirs = built.split(" ", 1), manual.split(" ", 1)
        assert ours[0] == theirs[0]
        assert [float(a) for a in ours[1].split(",")] == [float(b) for b in theirs[1].replace(" ", "").split(",")]


def test_every_qscv_builder_has_a_golden_case() -> None:
    assert {case["builder"] for case in BUILDERS["cases"]} == {"qsv", "qst", "qsm", "qsl", "qso", "qsc", "qsr", "qsz"}


def test_measurement_mode_form() -> None:
    """``MM 13[,chnum]`` takes at most one channel (PG PDF 470; Table 3-17 ``MM 13,gate``, PDF 243)."""
    assert flex.mm(13, [3]) == "MM 13,3" and flex.mm(13, []) == "MM 13"
    assert flex.QSCV_MODE == 13 and 13 in flex.MEASUREMENT_MODES and 13 in flex.OPTIONAL_CHANNEL_MODES
    with pytest.raises(ValueError):
        flex.mm(13, [3, 4])


@pytest.mark.parametrize("call", [
    lambda: flex.qsv(1, "log", 0, 0, 5, 1, 4, 0.1),  # mode 1 or 3 only (error 246)
    lambda: flex.qsv(1, "single", 0, 0, 0, 1, 4, 0.1),  # start = stop
    lambda: flex.qsv(1, "single", 0, 0, 101, 1, 4, 0.1),  # +-100 V
    lambda: flex.qsv(1, "single", 0, 0, 5, 0, 4, 0.1),  # cvoltage > 0
    lambda: flex.qsv(1, "single", 0, 0, 5, 10.5, 4, 0.1),  # cvoltage <= 10 V
    lambda: flex.qsv(1, "single", 0, 0, 5, 1, 0, 0.1),  # step 1-1001
    lambda: flex.qsv(1, "single", 0, 0, 5, 1, 1002, 0.1),
    lambda: flex.qsv(1, "single", 0, 0, 5, 1, 4, 0),  # compliance always sent, never 0
    lambda: flex.qsv(1, "single", 3, 0, 5, 1, 4, 0.1),  # not a voltage ranging code
    lambda: flex.qst(0.01, 0.1, 0, 0, 0),  # cinteg >= 1/60 s
    lambda: flex.qst(0.1, 2.5, 0, 0, 0),  # linteg <= 2 s
    lambda: flex.qst(0.1, 0.1, 0.005, 0, 0),  # hold in 10 ms steps
    lambda: flex.qst(0.1, 0.1, 0, 0.00005, 0),  # delay1 in 0.1 ms steps
    lambda: flex.qst(0.1, 0.1, 0, 0, 70),  # delay2 <= 65.535 s
    lambda: flex.qsm(True, "last"),  # QSM post 1 or 2
    lambda: flex.qso(True),  # QSO 1 needs its channel (error 247)
    lambda: flex.qso(False, 5),  # QSO 0 takes no channel
    lambda: flex.qso(True, 5, 0),
    lambda: flex.qsc("4156"),
    lambda: flex.qsr(-8),  # -9..-14 (error 241)
    lambda: flex.qsr(-15),
    lambda: flex.qsz(3),
])
def test_out_of_domain_parameters_are_refused(call: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        call()


def test_type_errors() -> None:
    with pytest.raises(TypeError):
        flex.qsm(2, "start")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        flex.qsl(1, 1)  # type: ignore[arg-type]


def test_range_codes() -> None:
    assert flex.QSCV_RANGE_CODES == {-9: 1e-11, -10: 1e-10, -11: 1e-9, -12: 1e-8, -13: 1e-7, -14: 1e-6}
    assert flex.QSCV_SWEEP_MODES == {"single": 1, "double": 3} and flex.QSCV_MAX_STEPS == 1001
