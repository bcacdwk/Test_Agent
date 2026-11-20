"""MFCMU and SCUU FLEX builders (``driver/flex/cmu.py``, ``driver/flex/switch.py``; WP8.1): golden strings from the
Programming Guide's examples (``tests/fixtures/flex/cmu/builders.yaml``), the manual's parameter domains, the tables
the builders encode, and their page citations (the generic citation/driver-map checks live in
``test_driver_flex.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "cmu" / "builders.yaml"
ENTRIES: list[dict[str, Any]] = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))


def _numbers(text: str) -> list[float]:
    return [float(v) for v in text.split(" ", 1)[1].split(",")]


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["expect"])
def test_golden_strings(entry: dict[str, Any]) -> None:
    built = getattr(flex, entry["builder"])(*entry["args"])
    assert built == entry["expect"]
    assert "PDF " in entry["source"]
    manual = entry.get("manual")
    if manual is not None:  # same command, same values; the builder writes numbers or defaults differently
        assert built.split()[0] == manual.split()[0]
        ours, theirs = _numbers(built), _numbers(manual)
        n = min(len(ours), len(theirs))
        assert ours[:n] == pytest.approx(theirs[:n])
        defaults = entry.get("defaults", [0.0] * 8)  # a parameter one side leaves out takes its default
        assert ours[n:] + theirs[n:] == defaults[: len(ours[n:] + theirs[n:])]


def test_every_mfcmu_and_scuu_builder_has_a_golden_string() -> None:
    covered = {entry["builder"] for entry in ENTRIES}
    cmu = {"imp", "fc", "acv", "dcv", "rc", "act", "lmn", "wdcv", "wtdcv", "wmdcv", "wfc", "wtfc", "wmfc", "wacv",
           "wtacv", "wmacv", "pdcv", "ptdcv", "pwdcv", "mdcv", "mtdcv", "adj", "adj_q", "corrl", "clcorr", "corr_q",
           "dcorr", "corrdt", "corrst", "corrst_q", "ssp", "ssl"}
    assert cmu <= covered


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.imp(99),  # not in Table 4-16
        lambda: flex.fc(7, 999.0),  # 1 kHz minimum (Table 4-18)
        lambda: flex.fc(7, 5.000001e6),
        lambda: flex.fc(7, float("nan")),
        lambda: flex.acv(7, 0.251),  # 250 mV maximum
        lambda: flex.acv(7, -0.01),
        lambda: flex.dcv(7, 25.001),  # MFCMU +-25 V (the SCUU SMU form is out of scope)
        lambda: flex.dcv(7, -26),
        lambda: flex.rc(7, 1),  # modes 0 and 2
        lambda: flex.rc(7, 0, 50),  # auto takes no range
        lambda: flex.rc(7, 2),  # fixed needs one
        lambda: flex.rc(7, 2, -1),
        lambda: flex.act(1, 2),
        lambda: flex.act(0, 1024),
        lambda: flex.act(2, 101),
        lambda: flex.lmn(2),
        lambda: flex.wdcv(7, 5, 0, 1, 11),
        lambda: flex.wdcv(7, 1, 0, 30, 11),
        lambda: flex.wdcv(7, 1, 0, 1, 1002),  # 1001 steps maximum
        lambda: flex.wdcv(7, 2, -1, 1, 11),  # log across polarity
        lambda: flex.wtdcv(0, 65.536),  # WTDCV delay 65.535 s maximum
        lambda: flex.wtdcv(0, 0.1, 0, 0.2),  # Tdelay > delay
        lambda: flex.wtdcv(0, 0, 1.1),
        lambda: flex.wtfc(655.36, 0),
        lambda: flex.wtacv(0, 0.1, 0, 0, 65.536),
        lambda: flex.wmdcv(3, 1),
        lambda: flex.wmfc(1, 0),
        lambda: flex.wmacv(0, 1),
        lambda: flex.wfc(7, 1, 500, 1e6, 11),
        lambda: flex.wacv(7, 1, 0, 0.3, 11),
        lambda: flex.wacv(7, 2, 0, 0.1, 11),  # log from 0
        lambda: flex.pdcv(7, 0, 26),
        lambda: flex.ptdcv(0, 0.007),  # 8 ms minimum width
        lambda: flex.ptdcv(0, 0.01, 0.011),  # period >= width + 2 ms
        lambda: flex.ptdcv(0, 0.2, 0.205),  # period >= width + 10 ms above 100 ms
        lambda: flex.ptdcv(0, 0.01, 0.005),
        lambda: flex.ptdcv(0, 0.01, 0.02, 0.02),  # Tdelay <= width
        lambda: flex.pwdcv(7, 2, 0, -1, 1, 11),  # linear only (error 283)
        lambda: flex.pwdcv(7, 1, 0, -1, 1, 0),
        lambda: flex.mdcv(7, 0, 30),
        lambda: flex.mdcv(7, 0, 1, -26),
        lambda: flex.mtdcv(0, 0.007, 10),  # 8 ms minimum interval
        lambda: flex.mtdcv(0, 0.01, 10002),
        lambda: flex.mtdcv(656, 0.01, 10),
        lambda: flex.adj(7, 3),
        lambda: flex.corrl(7, 6e6),
        lambda: flex.clcorr(7, 3),
        lambda: flex.corr_q(7, "phase"),  # phase compensation is ADJ?, not CORR?
        lambda: flex.dcorr(7, "open", 400, 0, 0),  # open uses Cp-G (100)
        lambda: flex.dcorr(7, "short", 100, 0, 0),
        lambda: flex.dcorr(7, "load", 400, float("inf"), 0),
        lambda: flex.corrdt(7, 500, 0, 0, 0, 0, 0, 0),
        lambda: flex.ssp(7, 5),  # paths 1-4
        lambda: flex.ssp(7, 0),  # no SSP path opens the outputs
        lambda: flex.ssp(2, 4),  # an SCUU MFCMU needs two SMU slots below it
        lambda: flex.ssp(305, 4),  # 305 is not a channel of slot 3's first subchannel
        lambda: flex.ssl(1, True),
        lambda: flex.mm(19, [7, 3]),  # pulsed spot C: one channel
    ],
)
def test_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize("call", [lambda: flex.imp(100.0), lambda: flex.corrst(7, "open", 1),
                                  lambda: flex.ssl(7, 1), lambda: flex.act(0, 2.0), lambda: flex.ssp(True, 4)])
def test_builders_reject_wrong_types(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_tables_follow_the_manual() -> None:
    assert len(flex.IMP_MODES) == 20 and flex.IMP_MODES[100] == ("Cp", "G") and flex.IMP_INITIAL == 100
    assert flex.IMP_MODES[11] == ("Z", "theta_deg") and flex.IMP_MODES[200] == ("Cs", "Rs")
    assert flex.CMU_FREQ_HZ == (1e3, 5e6) and (flex.CMU_MAX_AC_V, flex.CMU_MAX_DC_V) == (0.25, 25.0)
    assert flex.SSP_PATHS == {1: ("smu", "open"), 2: ("open", "smu"), 3: ("smu", "smu"), 4: ("cmu", "cmu")}
    assert flex.DCORR_MODES == {"open": 100, "short": 400, "load": 400}
    assert len(flex.CLCORR_DEFAULT_FREQS_HZ) == 23 and flex.CLCORR_DEFAULT_FREQS_HZ[-1] == 5e6
    assert (flex.LRN_ADJ_MODE, flex.LRN_SCUU_PATH, flex.LRN_ADJ_ITEM, flex.LRN_SCUU_ITEM) == (90, 81, "ADJ", "SSP")
    assert flex.ADJ_MODES == {0: "auto", 1: "manual", 2: "load_adaptive"}
    assert sorted(flex.CORR_RESULTS) == [0, 1, 2]
    assert flex.MEASUREMENT_MODES == {1, 2, 10, 16, 17, 18, 19, 20, 22, 23, 26}  # SMU modes: WP7.2, WP7.4


def test_mm18_takes_the_mfcmu_and_up_to_nine_smus() -> None:
    assert flex.mm(18, [7, 3, 4, 5, 6]) == "MM 18,7,3,4,5,6"
    with pytest.raises(ValueError):
        flex.mm(18, list(range(1, 11)) + [1001])


def test_sweep_timing_sends_optional_delays_up_to_the_last_non_zero_one() -> None:
    assert flex.wtdcv(0, 0, 0, 0, 0.5) == "WTDCV 0,0,0,0,0.5"
    assert flex.wtfc(0, 0.2, 0.1) == "WTFC 0,0.2,0.1"
    assert flex.wtacv(0, 100.0) == "WTACV 0,100"  # WTACV/WTFC delays reach 655.35 s, WTDCV 65.535 s
    assert flex.ptdcv(0, 0.05, 0.06, 0.01) == "PTDCV 0,0.05,0.06,0.01"


def test_ssp_accepts_the_subchannel_form() -> None:
    assert flex.ssp(701, 3) == "SSP 701,3" and flex.ssl(10, True) == "SSL 10,1"
