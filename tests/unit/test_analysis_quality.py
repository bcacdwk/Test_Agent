"""Quality classification (``assess_quality``, rules R-QUAL-*): counts, fractions, verdicts, noise."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis import MIN_SNR, RunData, assess_quality, noise_sigma, signal_to_noise
from b1500_test_agent.models.analysis import TrustPolicy
from b1500_test_agent.models.recipe import QualityCriteria
from tests.unit.analysis_helpers import idvg_table, linear_region_id, manifest
from tests.unit.helpers import assert_roundtrip

VG = np.linspace(-1.0, 3.0, 101)


def run(drain_status: list[str] | None = None, gate_status: list[str] | None = None, drain_i: object = None) -> RunData:
    current = linear_region_id(VG) if drain_i is None else drain_i
    return RunData(manifest(), idvg_table(VG, current, drain_status=drain_status, gate_status=gate_status))


def statuses(**at: str) -> list[str]:
    letters = ["N"] * 101
    for index, letter in at.items():
        letters[int(index[1:])] = letter
    return letters


def test_clean_run_is_ok() -> None:
    report = assess_quality(run())
    assert report.verdict == "ok" and report.points == 101
    assert report.counts == {"N": 202}
    assert report.columns == {"gate_I": {"N": 101}, "drain_I": {"N": 101}}
    assert report.fractions == {"ok": 1.0, "limited": 0.0, "untrusted": 0.0}
    assert report.warnings == [] and report.noise["drain_I"] == 0.0 and "drain_I" not in report.snr
    assert_roundtrip(report)


def test_compliance_points_make_the_run_limited() -> None:
    report = assess_quality(run(drain_status=statuses(i90="C", i91="C"), gate_status=statuses(i90="T", i91="T")))
    assert report.verdict == "limited"
    assert report.counts == {"C": 2, "N": 198, "T": 2}
    assert report.columns["drain_I"] == {"C": 2, "N": 99}
    assert report.fractions["limited"] == pytest.approx(2 / 101) and report.fractions["untrusted"] == 0.0
    assert any(w.startswith("drain_I: 2 point(s) with status C (limited") for w in report.warnings)


@pytest.mark.parametrize("letter", ["V", "X", "F", "D", "G", "S", "U", "W", "Z"])
def test_untrusted_or_unknown_letters_make_the_run_untrusted(letter: str) -> None:
    report = assess_quality(run(drain_status=statuses(i50=letter, i60="C")))
    assert report.verdict == "untrusted"
    assert report.counts[letter] == 1 and report.fractions["untrusted"] == pytest.approx(1 / 101)
    assert any("untrusted, extraction refused unless forced" in w for w in report.warnings)


def test_the_recipe_policy_decides_the_classes() -> None:
    data = run(drain_status=statuses(i50="X"))
    assert assess_quality(data).verdict == "untrusted"
    x_limited = QualityCriteria(limited=["C", "T", "X"], untrusted=["V", "F", "D", "G", "S", "U"])
    assert assess_quality(data, x_limited).verdict == "limited"
    assert assess_quality(data, TrustPolicy()).verdict == "untrusted"


def test_empty_table_is_untrusted() -> None:
    report = assess_quality(RunData(manifest(), idvg_table([], [])))
    assert report.verdict == "untrusted" and report.points == 0 and report.counts == {}
    assert "no points" in report.warnings[0]


def test_noise_estimate_recovers_white_noise() -> None:
    rng = np.random.default_rng(7)
    x = np.linspace(0.0, 1.0, 2001)
    sigma = 1e-9
    values = 1e-6 * x + 2e-7 * x**2 + sigma * rng.standard_normal(x.size)
    estimate = noise_sigma(values)
    assert estimate == pytest.approx(sigma, rel=0.1)
    assert signal_to_noise(values, estimate) == pytest.approx((values.max() - values.min()) / estimate)
    assert noise_sigma(values[:6]) is None and noise_sigma(values[:7]) is not None
    assert signal_to_noise(values, 0.0) is None and signal_to_noise(values, None) is None


def test_noise_floor_is_flagged_per_column() -> None:
    rng = np.random.default_rng(3)
    report = assess_quality(run(drain_i=1e-11 * rng.standard_normal(101)))
    assert report.verdict == "ok"  # status letters are fine; the noise flag is a warning
    assert report.snr["drain_I"] < MIN_SNR
    assert any(w.startswith("drain_I: signal range is only") for w in report.warnings)
    healthy = assess_quality(run(drain_i=linear_region_id(VG) * (1 + 1e-3 * rng.standard_normal(101))))
    assert healthy.snr["drain_I"] > 100 * MIN_SNR


def test_noise_ignores_limited_points() -> None:
    clamped = linear_region_id(VG)
    clamped[95:] = 1e-4  # compliance clamp, flagged C
    report = assess_quality(run(drain_status=["N"] * 95 + ["C"] * 6, drain_i=clamped))
    assert report.noise["drain_I"] == 0.0
