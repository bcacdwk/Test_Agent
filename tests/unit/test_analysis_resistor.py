"""``resistance`` on analytic I-V lines (WP2.2): R, linearity and offset, the open/short/in_range classification
with its thresholds, the compliance and noise-floor readings, and the trust rules."""

from __future__ import annotations

import numpy as np
import pytest

from b1500_test_agent.analysis.resistor import resistance
from b1500_test_agent.errors import InvalidInputError
from tests.unit.analysis_helpers import iv_table, run_of
from tests.unit.helpers import assert_roundtrip

V = np.linspace(-0.1, 0.1, 21)
INVALID = 199.999e99


def contact(current: np.ndarray, *, status: list[str] | None = None, v: np.ndarray = V):
    table = iv_table({"a_V": v}, {"a_I": current}, status={"a_I": status} if status else None)
    return run_of(table, "basic.contact_resistor")


@pytest.mark.parametrize(("r_ohm", "expected"), [(1e5, "in_range"), (50.0, "short"), (5e9, "open")])
def test_resistance_linearity_offset_and_classification(r_ohm: float, expected: str) -> None:
    rng = np.random.default_rng(1)
    current = V / r_ohm * (1 + 1e-6 * rng.standard_normal(V.size)) + 2e-12  # 1e-6 relative noise + offset
    r, r2, offset = resistance(contact(current))
    assert (r.quantity, r.unit, r.classification, r.bound) == ("resistance", "Ohm", expected, "exact")
    assert r.value == pytest.approx(r_ohm, rel=1e-4)
    assert (r2.quantity, r2.unit) == ("linearity_r2", "1") and r2.value > 0.9999
    assert (offset.quantity, offset.unit) == ("offset_current", "A")
    assert offset.value == pytest.approx(2e-12, abs=max(1e-12, 1e-6 * 0.1 / r_ohm))  # within the noise
    assert r.window is not None and (r.window.low, r.window.high) == (-0.1, 0.1) and r.points_used == 21
    assert_roundtrip(r)


def test_thresholds_are_options() -> None:
    current = V / 1e5
    assert resistance(contact(current), r_open_ohm=5e4)[0].classification == "open"
    assert resistance(contact(current), r_short_ohm=2e5)[0].classification == "short"


def test_a_noise_floor_reads_open_with_a_lower_bound() -> None:
    rng = np.random.default_rng(4)
    sigma = 5e-12
    r, offset = resistance(contact(sigma * rng.standard_normal(V.size)))
    assert r.classification == "open" and r.bound == "lower" and r.outcome == "ok"
    assert r.value == pytest.approx(0.2 / (10 * r.fit["noise_a"]), rel=1e-6) and r.value > 1e9
    assert "noise floor" in r.warnings[0] and offset.quantity == "offset_current"


def test_compliance_reads_short_with_an_upper_bound_and_aborted_rows() -> None:
    current = np.full(V.size, INVALID)
    status = ["V"] * V.size
    current[0], status[0] = -1e-3, "C"  # compliance at the first step, then the automatic abort
    [r] = resistance(contact(current, status=status))
    assert (r.classification, r.bound, r.outcome) == ("short", "upper", "ok")
    assert r.value == pytest.approx(100.0) and r.points_excluded == {"C": 1, "aborted": 20}
    weak = resistance(contact(current * 1e-3, status=status))[0]  # 1 uA compliance: R <= 100 kOhm, undecidable
    assert weak.outcome == "failed" and "r_short_ohm" in weak.error


@pytest.mark.parametrize("letter", ["X", "V"])
def test_untrusted_points_refuse_unless_forced(letter: str) -> None:
    current = V / 1e5
    status = ["N"] * V.size
    status[5] = letter
    refused = resistance(contact(current, status=status))
    assert len(refused) == 1 and refused[0].outcome == "refused" and "untrusted" in refused[0].error
    forced = resistance(contact(current, status=status), force=True)
    assert forced[0].classification == "in_range" and forced[0].forced_on_untrusted


def test_negative_conductance_fails_and_columns_are_checked() -> None:
    [r] = resistance(contact(-V / 1e5))
    assert r.outcome == "failed" and "not a resistor" in r.error
    with pytest.raises(InvalidInputError):
        resistance(contact(V / 1e5), y="a_V")
