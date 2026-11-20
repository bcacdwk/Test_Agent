"""HV-SPGU FLEX builders (``driver/flex/spgu.py``, WP9.1): golden strings from the Programming Guide examples
(``tests/fixtures/flex/spgu/builders.yaml``), the ALWG data blocks of Tables 2-4/2-5
(``tests/fixtures/flex/spgu/alwg_blocks.yaml``, shared with the simulator's decoder tests), domain checks, and the
builders that accept less than the manual on purpose (no free run)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from b1500_test_agent.driver import flex
from b1500_test_agent.models.spgu import AlwgPattern, AlwgVector

pytestmark = pytest.mark.spgu

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "flex" / "spgu"


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def patterns_of(items: list[dict[str, Any]]) -> list[AlwgPattern]:
    return [AlwgPattern(initial_v=p["initial_v"],
                        vectors=[AlwgVector(dt_s=dt, v=v, switch_closed=closed) for dt, v, closed in p["vectors"]])
            for p in items]


BUILDERS = load("builders.yaml")


@pytest.mark.parametrize("case", BUILDERS["cases"], ids=lambda c: f"{c['builder']}-{c['expect']}")
def test_builder_matches_the_golden_string(case: dict[str, Any]) -> None:
    built = getattr(flex, case["builder"])(*case["args"])
    assert built == case["expect"]
    assert 141 <= case["pdf"] <= 524  # the SPGU chapters and command pages of the Programming Guide
    manual = case.get("manual")
    if manual is not None:  # the manual's example, numerically equal (blanks and number forms differ)
        ours, theirs = built.split(" ", 1), manual.split(" ", 1)
        assert ours[0] == theirs[0]
        assert [float(a) for a in ours[1].split(",")] == [float(b) for b in theirs[1].replace(" ", "").split(",")]


@pytest.mark.parametrize("case", BUILDERS["constants"], ids=lambda c: c["name"])
def test_whole_command_constants(case: dict[str, Any]) -> None:
    assert getattr(flex, case["name"]) == case["expect"]


ALWG = load("alwg_blocks.yaml")


@pytest.mark.parametrize("case", ALWG["patterns"], ids=lambda c: c["name"])
def test_alw_pattern_block_follows_table_2_4(case: dict[str, Any]) -> None:
    header, block = flex.alw(101, patterns_of(case["patterns"]))
    assert header == f"ALW 101,{len(block)}"
    if "hex" in case:
        assert block.hex() == "".join(case["hex"].split())
    if "length" in case:
        assert len(block) == case["length"]


@pytest.mark.parametrize("case", ALWG["sequences"], ids=lambda c: c["name"])
def test_als_sequence_block_follows_table_2_5(case: dict[str, Any]) -> None:
    header, block = flex.als([tuple(c) for c in case["cycles"]])
    assert header == f"ALS {case['length']}" and block.hex() == "".join(case["hex"].split())


def test_the_switch_bit_and_time_share_one_word() -> None:
    _, block = flex.alw(102, patterns_of([{"initial_v": 0.0, "vectors": [[0.67108863, 40.0, True]]}]))
    assert block[-8:].hex() == "02625a00" + "a7fffff6"  # 40 V; switch closed + (2^26 - 1) x 10 ns


@pytest.mark.parametrize(
    "call",
    [
        lambda: flex.sprm(0, 1),  # free run is never built (R-PULSE-01)
        lambda: flex.sprm(1, 0),
        lambda: flex.sprm(1, 1_000_001),
        lambda: flex.sprm(1, 2.5),
        lambda: flex.sprm(2, 1e-7),
        lambda: flex.sprm(2, 31_556_927.0),
        lambda: flex.sim(2),
        lambda: flex.spm(101, 4),
        lambda: flex.spm(103, 1),  # not a B1500 channel number
        lambda: flex.spt(101, 0, 0, 1e-6, 2e-8),  # src 1 or 2
        lambda: flex.spt(101, 1, -1e-9, 1e-6, 2e-8),
        lambda: flex.spt(101, 1, 0, 5e-9, 2e-8),  # width below 10 ns
        lambda: flex.spt(101, 1, 0, 1e-6, 5e-9),  # leading below 8 ns
        lambda: flex.spt(101, 1, 0, 1e-6, 2e-8, 0.5),  # trailing above 0.4 s
        lambda: flex.spv(101, 3, 0, 1),
        lambda: flex.spv(101, 1, 0, 40.5),
        lambda: flex.spv(101, 1, -41, 0),
        lambda: flex.spv(101, 0, 1, 2),  # a DC source has no peak
        lambda: flex.spper(1e-8),
        lambda: flex.spper(11.0),
        lambda: flex.ser(101, 0.05),
        lambda: flex.ser(101, 2e6),
        lambda: flex.spupd([]),
        lambda: flex.spupd([101, 101]),
        lambda: flex.spupd(list(range(1, 11)) + [101]),  # 11 > 10 (and 1 == 101)
        lambda: flex.odsw(101, 2),
        lambda: flex.odsw(101, 1, 2),
        lambda: flex.odsw(101, 1, None, 1e-6, 1e-6),  # timing needs the normal state
        lambda: flex.odsw(101, 1, 0, 1e-6, None),
        lambda: flex.odsw(101, 1, 0, 0, 5e-8),  # width below 100 ns
        lambda: flex.stgp(101, 4),
        lambda: flex.corrser_q(101, 2, 0, 5e-6, 1),
        lambda: flex.corrser_q(101, 0, 0, 4e-6, 1),  # interval below 5 us
        lambda: flex.corrser_q(101, 0, 0, 2e-3, 1),
        lambda: flex.corrser_q(101, 0, 0, 5e-6, 0),
        lambda: flex.corrser_q(101, 0, 0, 5e-6, 65536),
        lambda: flex.spv(101, 1, 0, float("nan")),
        lambda: flex.als([]),
        lambda: flex.als([(0, 1)]),
        lambda: flex.als([(1, 0)]),
        lambda: flex.als([(1, 1_048_577)]),
        lambda: flex.als([(513, 1)]),
    ],
)
def test_builders_reject_values_outside_the_manual_domain(call) -> None:
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize(
    ("initial", "vectors"),
    [
        (0.0, [[1e-8, 0.0005, True]]),  # not on the 1 mV resolution
        (0.0, [[1e-8, 40.001, True]]),
        (40.5, [[1e-8, 0.0, True]]),
        (0.0, [[5e-9, 1.0, True]]),  # below 10 ns
        (0.0, [[1.5e-8, 1.0, True]]),  # not on the 10 ns grid
        (0.0, [[0.6710887, 1.0, True]]),  # above (2^26 - 1) x 10 ns
    ],
)
def test_alw_refuses_data_outside_table_2_4(initial: float, vectors: list[list[Any]]) -> None:
    with pytest.raises(ValueError):
        flex.alw(101, patterns_of([{"initial_v": initial, "vectors": vectors}]))


def test_alw_counts_patterns_and_vectors() -> None:
    one = {"initial_v": 0.0, "vectors": [[1e-8, 1.0, True]]}
    flex.alw(101, patterns_of([one] * 512))  # 512 patterns, 512 vectors <= 1024 - 512
    with pytest.raises(ValueError, match="1 to 512 patterns"):
        flex.alw(101, patterns_of([one] * 513))
    with pytest.raises(ValueError, match="exceed 1024"):
        flex.alw(101, patterns_of([{"initial_v": 0.0, "vectors": [[1e-8, 1.0, True]] * 1024}]))
    with pytest.raises(ValueError, match="1 to 512 patterns"):
        flex.alw(101, [])


@pytest.mark.parametrize("call", [lambda: flex.sim(True), lambda: flex.spm(101, 1.0), lambda: flex.spv(101, 1, "1"),
                                  lambda: flex.corrser_q(101, 0, 0, 5e-6, 1.0)])
def test_builders_reject_wrong_types(call) -> None:
    with pytest.raises(TypeError):
        call()


def test_spgu_builders_never_combine_commands() -> None:
    samples = [flex.sim(0), flex.spm(101, 3), flex.spt(101, 1, 0, 1e-6, 2e-8, 2e-8), flex.spv(101, 1, 0, 3),
               flex.spper(1e-5), flex.sprm(1, 2), flex.ser(101, 1e6), flex.spupd([101, 102]), flex.odsw(101, 0),
               flex.stgp(101, 0), flex.corrser_q(101, 0, 0, 5e-6, 1), flex.SRP, flex.SPP,
               flex.als([(1, 1)])[0], flex.alw(101, patterns_of([{"initial_v": 0.0,
                                                                   "vectors": [[1e-8, 1.0, True]]}]))[0]]
    for text in samples:
        assert ";" not in text and "\n" not in text, text
    assert flex.SPRM_COUNT == 1 and flex.SPRM_DURATION == 2 and flex.SIM_PG == 0 and flex.SIM_ALWG == 1
    assert sorted(flex.SPM_MODES) == [0, 1, 2, 3] and flex.CORRSER_MEASURE_ONLY == 0
